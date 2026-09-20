"""CLI for development and the detached installer worker."""
import argparse
import json
import os
from pathlib import Path
import sys

from .core import HostError, Store, doctor, provision_wine, work


def parse_product(text):
    """Read NAME:RECOVERY[:ACTIVATIONS_LEFT] without accepting licence material."""
    parts = text.split(':')
    if len(parts) not in (2, 3) or not parts[0].strip():
        raise ValueError('Expected NAME:RECOVERY[:ACTIVATIONS_LEFT], for example '
                         '"ExampleSynth:limited-activations:3"')
    product = {'name': parts[0].strip(), 'recovery': parts[1].strip()}
    if len(parts) == 3:
        if not parts[2].strip().isdigit():
            raise ValueError('Remaining activations must be a whole number: ' + text)
        product['activations_remaining'] = int(parts[2])
    return product


def render_components(index):
    """List the parts a recipe can be assembled from, and what each solves."""
    lines = ['Components you can build a recipe from:', '']
    for item in index:
        lines.append('%s  [%s]' % (item['reference'], item['tier']))
        lines.append('  ' + (item['purpose'] or item['name']))
        if item['capabilities']:
            lines.append('  can: ' + ', '.join(item['capabilities']))
        if item['requires']:
            lines.append('  needs: ' + ', '.join(item['requires']))
        lines.append('')
    return '\n'.join(lines)


def confirmation(args, environment):
    """Require the exact phrase for this environment, and say what it is."""
    from . import licensing
    record = licensing.read(environment)
    expected = licensing.required_confirmation((record or {}).get('products', []))
    if args.confirm is None:
        raise ValueError('This environment holds activations. Read what it protects with '
                         '"licensing status", then repeat the phrase exactly:\n  --confirm ' + repr(expected))
    return args.confirm


def main():
    parser = argparse.ArgumentParser(prog="plugg")
    parser.add_argument("--data", type=Path, help="Separate managed library (use for development)")
    parser.add_argument("--publish-dir", type=Path, help="Publication root on first library creation")
    parser.add_argument("--bridge-dir", type=Path, help="Native bridge build directory on first library creation")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("gui")
    commands.add_parser("doctor")
    commands.add_parser("list")
    commands.add_parser("prepare")
    softube_join = commands.add_parser('softube-join', help='Set up Softube in an existing shared iLok environment')
    softube_join.add_argument('installer', type=Path)
    softube_join.add_argument('--environment', type=Path, required=True)
    softube_stage = commands.add_parser('softube-stage', help='Extract reviewed Softube files without installing them')
    softube_stage.add_argument('installer', type=Path)
    softube_stage.add_argument('--output', type=Path, required=True)
    softube_stage.add_argument('--compare-environment', type=Path,
                               help='Read-only comparison with an existing shared environment')
    install = commands.add_parser("install")
    install.add_argument("installer", type=Path)
    install.add_argument("--background", action="store_true")
    worker = commands.add_parser("worker")
    worker.add_argument("job")
    worker.add_argument("--rescan", action="store_true")
    check = commands.add_parser("rescan")
    check.add_argument("job")
    cancel = commands.add_parser("cancel")
    cancel.add_argument("job")
    stop = commands.add_parser('stop', help='End the vendor applications running in an environment')
    stop.add_argument('job')
    reset = commands.add_parser('helper-reset', help='Clear a helper status left behind by an interrupted operation')
    reset.add_argument('job')
    retire = commands.add_parser('archive', help='Retire an installation, freeing its vendor slot')
    retire.add_argument('job')
    retire.add_argument('--restore', action='store_true', help='Bring an archived installation back')
    drop = commands.add_parser('discard', help='Forget a finished attempt; its environment is kept')
    drop.add_argument('job')
    forget = commands.add_parser('forget', help='Retire a plug-in you have uninstalled')
    forget.add_argument('--plugin', help='Managed plug-in id, as shown by list')
    forget.add_argument('--environment', dest='env_id',
                        help='Retire every plug-in published from this environment')
    environment_command = commands.add_parser('environment', help='Name an environment (its folder and ID stay the same)')
    environment_command.add_argument('action', choices=('rename', 'helpers', 'use-helper'))
    environment_command.add_argument('environment_id')
    environment_command.add_argument('name', nargs='?', default='',
                                     help='rename: new name, empty to clear. use-helper: the name its card shows')
    environment_command.add_argument('--program', help='use-helper: the program, as listed by "helpers"')
    names = commands.add_parser('rename-bundles',
                                help='Republish anything still named after its hash, under its own name')
    names.add_argument('--apply', action='store_true',
                       help='Do it. Without this, prints what would change and touches nothing.')
    relink = commands.add_parser('relink-bundles',
                                 help='Move published plug-ins onto bridge files the library owns')
    relink.add_argument('--apply', action='store_true',
                        help='Do it. Without this, prints what would change and touches nothing.')
    vendor = commands.add_parser('vendor-worker')
    vendor.add_argument('job')
    vendor.add_argument('--refresh-only', action='store_true')
    recipe_command = commands.add_parser('recipe', help='Add, validate, inspect or apply local recipes')
    recipe_command.add_argument('action', choices=('add', 'init', 'list', 'validate', 'check', 'match',
                                                   'status', 'plan', 'apply', 'explain', 'components', 'setup-existing',
                                                   'leads'))
    recipe_command.add_argument('target', nargs='?')
    recipe_command.add_argument('--allow-electron-no-sandbox', action='store_true', help='Allow UA Connect helper compatibility flags; does not affect plug-ins')
    recipe_command.add_argument('--installer', type=Path, help='User-supplied installer for setup-existing')
    recipe_command.add_argument('--recipe-dir', type=Path, action='append', default=[])
    recipe_command.add_argument('--environment', type=Path)
    recipe_command.add_argument('--json', action='store_true', help='Machine-readable output')
    recipe_command.add_argument('--id', help='Recipe id for init, e.g. local.my-vendor')
    recipe_command.add_argument('--vendor', help='Vendor name for init')
    recipe_command.add_argument('--dependency', help='Runtime component for init; see recipe components')
    recipe_command.add_argument('--output', type=Path, help='Write the generated recipe here')
    ilok_command = commands.add_parser('ilok', help='Create the shared iLok environment, or install a vendor into it')
    ilok_command.add_argument('action', choices=('status', 'plan', 'create', 'install', 'open', 'update-ua-connect'))
    ilok_command.add_argument('installer', nargs='*',
                              help='create/plan: the PACE License Support MSI; install: one or more vendor installers; '
                                   'open: ilok, ua-connect or softube (default ilok)')
    ilok_command.add_argument('--vendor', help='install: the vendor name to record for this environment')
    runtime_command = commands.add_parser('runtime', help='List, assemble or select the Proton runtime new environments use')
    runtime_command.add_argument('action', choices=('list', 'plan', 'assemble', 'select', 'unselect'))
    runtime_command.add_argument('name', nargs='?', default='plugg-1')
    runtime_command.add_argument('--artifacts', type=Path, help='Directory of Wine modules you built with scripts/build-runtime-overlay.py (default: download the published ones, checked by hash)')
    runtime_command.add_argument('--base', type=Path, help='The UMU-Proton-10.0-4 directory to build from (default: the library\'s)')
    licence = commands.add_parser('licensing', help='Protect environments that hold product activations')
    licence.add_argument('action', choices=('status', 'protect', 'deactivated', 'unprotect', 'acknowledge',
                                            'backup', 'backups', 'restore'))
    licence.add_argument('--environment', type=Path, required=True)
    licence.add_argument('--product', action='append', default=[], metavar='NAME:RECOVERY[:LEFT]',
                         help='Product and how its activation recovers: reactivatable, '
                              'deactivate-first, limited-activations or unknown. Never record '
                              'serial numbers or credentials.')
    licence.add_argument('--note', help='Short reminder for yourself, not for licence details')
    licence.add_argument('--operation', help='Operation to acknowledge, such as recreate_prefix')
    licence.add_argument('--confirm', help='Exact confirmation phrase this environment requires')
    licence.add_argument('--label', help='Name for a new recovery point')
    licence.add_argument('--recovery-point', help='Recovery point to restore')
    args = parser.parse_args()
    try:
        if args.command == 'softube-join':
            from . import softube_setup
            print(json.dumps(softube_setup.join(args.installer, args.environment), indent=2))
            return 0
        if args.command == 'softube-stage':
            from . import softube_setup
            record = softube_setup.stage(args.installer, args.output)
            result = {'output': str(args.output), 'files': len(record['central_files']),
                      'installer_sha256': record['installer_sha256']}
            if args.compare_environment:
                result['comparison'] = softube_setup.compare(args.compare_environment, args.output)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == 'licensing':
            from . import licensing
            place = args.environment
            if args.action == 'status':
                print(json.dumps(licensing.status(place), indent=2))
            elif args.action == 'protect':
                if not args.product:
                    raise ValueError('Provide at least one --product NAME:RECOVERY[:LEFT]')
                print(json.dumps(licensing.protect(place, [parse_product(item) for item in args.product],
                                                   note=args.note), indent=2))
            elif args.action == 'deactivated':
                if not args.product:
                    raise ValueError('Name each product you deactivated with --product NAME')
                names = [item.split(':', 1)[0] for item in args.product]
                if args.confirm is None:
                    print('Deactivate with the vendor first (for iLok products, in iLok License Manager). '
                          'Then repeat with --confirm "' + licensing.deactivation_phrase(names) + '"')
                    return 1
                print(json.dumps(licensing.deactivated(place, names, args.confirm), indent=2))
            elif args.action == 'unprotect':
                print(json.dumps(licensing.unprotect(place, confirmation(args, place)), indent=2))
            elif args.action == 'acknowledge':
                if not args.operation:
                    raise ValueError('Provide --operation, such as recreate_prefix')
                print(json.dumps(licensing.acknowledge(place, args.operation, confirmation(args, place),
                                                        note=args.note), indent=2))
            elif args.action == 'backup':
                print(json.dumps(licensing.backup(place, label=args.label), indent=2))
            elif args.action == 'backups':
                print(json.dumps([{'id': item['id'], 'created': item.get('created')}
                                  for item in licensing.backups(place)], indent=2))
            else:
                if not args.recovery_point:
                    raise ValueError('Provide --recovery-point; list them with licensing backups')
                print(json.dumps(licensing.restore(place, args.recovery_point, confirmation(args, place)), indent=2))
            return 0
        if args.command == 'ilok':
            from . import ilok_setup
            store = Store(args.data)
            if args.action == 'status':
                directory = ilok_setup.current(store)
                print(json.dumps({'environment': str(directory) if directory else None,
                                  'group': ilok_setup.groups(store).get('groups', {}).get('ilok')}, indent=2))
                return 0
            if args.action == 'open':
                names = {'ilok': 'iLok License Manager', 'ua-connect': 'UA Connect', 'softube': 'Softube Central'}
                wanted = (args.installer or ['ilok'])[0]
                if wanted not in names:
                    raise ValueError('Open one of: ' + ', '.join(names))
                ilok_setup.open_manager(store, names[wanted])
                print(names[wanted] + ' is opening. Close it when you are done; the library refreshes then.')
                return 0
            if not args.installer:
                raise ValueError('Provide the installer')
            if args.action == 'update-ua-connect':
                from . import ua_setup
                directory = ilok_setup.current(store)
                if directory is None:
                    raise ValueError('There is no iLok environment yet.')
                print(json.dumps(ua_setup.update(Path(args.installer[0]), directory), indent=2))
                return 0
            if args.action in ('plan', 'create') and len(args.installer) != 1:
                raise ValueError(args.action + ' takes exactly one PACE installer')
            if args.action == 'plan':
                print(json.dumps(ilok_setup.preflight(store, Path(args.installer[0])), indent=2))
            elif args.action == 'create':
                print(json.dumps(ilok_setup.create(store, Path(args.installer[0])), indent=2))
            else:
                print(json.dumps(ilok_setup.install(store, args.installer, args.vendor), indent=2))
            return 0
        if args.command == 'runtime':
            from . import runtime_overlay
            root = Store(args.data).root
            if args.action == 'list':
                print(json.dumps(runtime_overlay.inventory(root), indent=2))
                return 0
            if args.action == 'unselect':
                runtime_overlay.select_for_new_environments(root, None)
                print('New environments will use the base UMU-Proton-10.0-4. Existing environments are unchanged.')
                return 0
            spec = runtime_overlay.overlay(args.name)
            if args.action == 'select':
                runtime_overlay.select_for_new_environments(root, args.name)
                print('New environments will use ' + args.name + '. Existing environments keep their runtime.')
                return 0
            base = args.base or root / 'runtimes' / 'proton-b246b81f09385d7b' / 'UMU-Proton-10.0-4'
            if args.action == 'assemble' and not args.base and not (base / 'proton').is_file():
                from . import recipes
                store = Store(args.data)
                recipes.provision(store, print, lambda: None)
            if args.action == 'plan':
                print(json.dumps(runtime_overlay.plan(spec, base, root / 'runtimes'), indent=2))
                return 0
            if args.artifacts:
                target = runtime_overlay.assemble(spec, base, args.artifacts, root / 'runtimes')
            else:
                import tempfile
                (root / 'runtimes').mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=root / 'runtimes', prefix='.modules-' + args.name + '-') as modules:
                    runtime_overlay.download_modules(Store(args.data), spec, modules)
                    target = runtime_overlay.assemble(spec, base, modules, root / 'runtimes')
            print('Assembled ' + str(target) + '\nNothing existing was changed. To use it for new environments:\n'
                  '  plugg runtime select ' + args.name)
            return 0
        if args.command == 'recipe':
            from . import recipe_engine
            if args.bridge_dir:
                raise ValueError('recipe does not use --bridge-dir')
            if args.action in ('list', 'check', 'status', 'components') and args.target:
                raise ValueError(args.action + ' does not take a target; use --recipe-dir for a catalogue directory')
            if args.environment and args.action not in ('plan', 'apply', 'status', 'setup-existing'):
                raise ValueError(args.action + ' does not use --environment')
            if args.recipe_dir and args.action == 'add':
                raise ValueError('add does not use --recipe-dir; recipes are added to the user configuration directory')
            if args.recipe_dir and args.action in ('validate', 'status'):
                raise ValueError(args.action + ' does not load catalogue directories')
            for directory in args.recipe_dir:
                if not directory.is_dir():
                    raise ValueError('Recipe directory does not exist or is not a directory: ' + str(directory))
            if args.action == 'status':
                if not args.environment: raise ValueError('Provide --environment')
                print(json.dumps(recipe_engine.status(args.environment), indent=2))
                return 0
            if args.action == 'leads':
                from . import leads
                found = leads.search(args.target or '')
                records = recipe_engine.catalogue([*recipe_engine.default_directories(), *args.recipe_dir])
                for product in found:
                    product['recipes_here'] = leads.recipes_for(product, records)
                if args.json:
                    print(json.dumps(found, indent=2))
                elif not found:
                    print('No leads match ' + repr(args.target or ''))
                else:
                    print('\n\n'.join(leads.render(product, product['recipes_here']) for product in found))
                return 0
            if args.action == 'init':
                from . import recipe_scaffold
                if not args.target:
                    raise ValueError('Provide the Windows VST3 or installer to write a recipe for')
                text = recipe_scaffold.scaffold(
                    args.target, identity=args.id, vendor=args.vendor,
                    dependency=args.dependency or recipe_scaffold.DEFAULT_DEPENDENCY)
                from . import leads
                native = leads.native(leads.for_vendor(args.vendor or Path(args.target).stem))
                if native:
                    print('Note: ' + ', '.join(product['name'] for product in native)
                          + ' has a native Linux build. Use that instead of bridging the Windows version'
                          + ' (see "plugg recipe leads").', file=sys.stderr)
                if args.output:
                    if args.output.exists():
                        raise ValueError('Refusing to overwrite ' + str(args.output))
                    args.output.write_text(text)
                    print('Wrote ' + str(args.output) + '\n\nNext:\n  plugg recipe validate '
                          + str(args.output) + '\n  plugg recipe explain ' + str(args.output))
                else:
                    print(text, end='')
                return 0
            if args.action == 'add':
                if not args.target: raise ValueError('Provide a recipe TOML path')
                print(json.dumps(recipe_engine.add_local(args.target), indent=2))
                return 0
            if args.action == 'validate':
                if not args.target: raise ValueError('Provide a recipe TOML path')
                record = recipe_engine.load(args.target)
                print(json.dumps({'reference': recipe_engine.reference(record), 'sha256': record['sha256']}, indent=2))
                return 0
            records = recipe_engine.catalogue([*recipe_engine.default_directories(), *args.recipe_dir])
            if args.action in ('explain', 'components'):
                from . import recipe_report
                if args.action == 'components':
                    index = recipe_report.component_index(records)
                    print(json.dumps(index, indent=2) if args.json else render_components(index))
                    return 0
                if not args.target:
                    raise ValueError('Provide id@revision, or a recipe TOML path')
                target = args.target
                if target not in records and Path(target).is_file():
                    candidate = recipe_engine.load(target)
                    reference = recipe_engine.reference(candidate)
                    records = {**records, reference: candidate}
                    target = reference
                if target not in records:
                    raise ValueError('No such recipe: ' + args.target)
                summary = recipe_report.report(records, target)
                print(json.dumps(summary, indent=2) if args.json else recipe_report.render(summary))
                return 0 if summary['verdict'] != 'refused' else 1
            if args.action == 'match':
                if not args.target: raise ValueError('Provide a Windows VST3 or helper EXE installer')
                print(json.dumps(recipe_engine.match_input(records, args.target), indent=2))
            elif args.action == 'setup-existing':
                from . import shared_setups
                if not args.target or not args.environment or not args.installer:
                    raise ValueError('Provide a recipe reference, --environment and --installer')
                print(json.dumps(shared_setups.execute(records, args.target, args.installer, args.environment, allow_electron_no_sandbox=args.allow_electron_no_sandbox), indent=2))
            elif args.action == 'check':
                print(json.dumps(recipe_engine.check(records), indent=2))
            elif args.action == 'list':
                print(json.dumps([{'reference': key, 'name': value['data']['name'], 'source': value['source']} for key,value in sorted(records.items())], indent=2))
            else:
                if not args.target or not args.environment: raise ValueError('Provide id@revision and --environment')
                plan = recipe_engine.plan(records, args.target, args.environment)
                print(json.dumps(recipe_engine.apply(plan) if args.action == 'apply' else plan, indent=2))
            return 0
        store = Store(args.data, args.publish_dir, args.bridge_dir)
        if args.command in (None, "gui"):
            from .gui import run
            # Programs the app starts inherit its working directory, and
            # Proton's container refuses one under /usr or other system paths.
            os.chdir(store.root)
            return run(store)
        if args.command == "doctor":
            print(json.dumps(doctor(store), indent=2))
        elif args.command == "list":
            print(json.dumps({"jobs": store.jobs(), "plugins": store.plugins()}, indent=2))
        elif args.command == "prepare":
            store.bridge()
            print(provision_wine(store, lambda x: print(x, flush=True)))
        elif args.command == "install":
            job = store.ingest(args.installer)
            if args.background:
                store.start(job)
            else:
                work(store, job)
            print(json.dumps(store.job(job), indent=2))
        elif args.command == 'stop':
            from .vendors import stop_helper
            print(json.dumps(stop_helper(store, args.job), indent=2))
        elif args.command == 'helper-reset':
            from .vendors import reset_helper_state
            print(json.dumps(reset_helper_state(store, args.job), indent=2))
        elif args.command == 'archive':
            # A vendor card has no archive control of its own, so retiring the
            # installation that holds a vendor's slot had no route at all. It
            # removes nothing: the environment, its files and its publications
            # stay exactly where they are, and --restore puts the card back.
            store.archive(args.job, not args.restore)
            print(json.dumps(store.job(args.job), indent=2))
        elif args.command == 'discard':
            print(json.dumps(store.discard(args.job), indent=2))
        elif args.command == 'forget':
            from .core import forget_plugin, forget_environment
            if bool(args.plugin) == bool(args.env_id):
                raise ValueError('Provide exactly one of --plugin or --environment')
            result = (forget_plugin(store, args.plugin) if args.plugin
                      else forget_environment(store, args.env_id))
            print(json.dumps(result, indent=2))
        elif args.command == 'environment':
            from . import environments, vendors
            if args.action == 'helpers':
                for program in vendors.helper_candidates(store.root / 'environments' / args.environment_id):
                    print(program)
            elif args.action == 'use-helper':
                if not args.program or not args.name:
                    raise ValueError('Give the program (--program, from "helpers") and the name its card should show')
                print(json.dumps(vendors.adopt_helper(store, args.environment_id, args.program, args.name), indent=2))
            else:
                name = environments.rename(store, args.environment_id, args.name)
                print(('Named ' + args.environment_id + ': ' + name) if name else ('Cleared the name of ' + args.environment_id))
        elif args.command == 'rename-bundles':
            from .core import rename_publications
            planned = rename_publications(store, apply=args.apply)
            if not planned:
                print('Every published plug-in already has a readable name.')
                return 0
            for item in planned:
                print('%-28s %s -> %s' % (item['name'], Path(item['from']).name, Path(item['to']).name))
            if args.apply:
                print('\nDone. Your DAW will rescan; the previous bundles are kept under bundles/ '
                      'and the record of what moved is in migration-backups/publication-names.json.')
            else:
                print('\nNothing has changed. Add --apply to do it. Close your DAW first: the paths '
                      'move, so it will rescan, and a project open at the time may not like that.')
        elif args.command == 'relink-bundles':
            from .core import relink_publications
            result = relink_publications(store, apply=args.apply)
            for item in result['planned']:
                build = ('bridge build ' + item['release'] + ' from ' + item['source']) if item['release'] else 'its DAW link'
                print('%-28s %s' % (item['name'], build))
            for item in result['problems']:
                print('%-28s NOT CHANGED: %s' % (item['name'], item['problem']))
            if not result['planned']:
                print('Every published plug-in already links only into the library.')
            elif args.apply:
                print('\nDone. Each plug-in keeps the bridge build it had; the links now lead into '
                      + str(store.root) + '. What they pointed to before is in ' + result['record'] + '.')
            else:
                print('\nNothing has changed. Add --apply to do it. The paths your DAW scans stay the same, '
                      'so there is no rescan; a plug-in already loaded keeps running on the files it opened.')
            return 1 if result['problems'] else 0
        elif args.command == 'vendor-worker':
            from .vendors import work as vendor_work
            vendor_work(store, args.job, args.refresh_only)
        elif args.command == "worker":
            work(store, args.job, args.rescan)
        elif args.command == "rescan":
            work(store, args.job, rescan=True)
        elif args.command == "cancel":
            store.cancel(args.job)
        return 0
    except (HostError, OSError, ValueError, RuntimeError) as exc:
        print(f"Plugg: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
