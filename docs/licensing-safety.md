# Protecting activated environments

An environment that holds product activations is not disposable. Recreating it, moving it or rewriting the Windows identity inside it can make a vendor treat it as a different computer. What that costs depends on the product, so Plugg does not guess. It records what you tell it, then refuses operations that would spend something you cannot get back.

Nothing here inspects, alters, emulates or bypasses a licensing check. It only stops this project's own operations from destroying your activations.

## Recovery classes

| Recovery | What it means | Example |
| --- | --- | --- |
| `reactivatable` | You can enter the serial again as often as needed. | Most download-and-serial products. |
| `deactivate-first` | Licences are bound to this environment as one machine. You get the seat back only if you deactivate before the change. | iLok/PACE products, vendor managers with a machine limit. |
| `limited-activations` | The serial validates a fixed number of times, ever. A lost activation is gone, and you buy the product again. | A serial with, say, five validations in total. |
| `unknown` | Not recorded. Plugg treats it as strictly as `limited-activations`. | Anything you have not classified yet. |

One environment can hold products from several classes. Plugg treats the environment according to its strictest product.

## What a recipe already knows

Whether a lost activation can be recovered is a fact about the vendor. It is the same for everyone who installs that product, so a recipe states it once:

~~~toml
[licensing]
vendor = "Klevgrand"
recovery = "deactivate-first"
note = "Three machines, one in use at a time. Uninstall through the Helper before rebuilding."
~~~

Every environment built from that recipe is protected from the moment Plugg creates it. Protection starts before there is anything to lose. The built-in Klevgrand recipe declares this, and vendor recipes should too.

A recipe may **not** declare `activations_remaining`. How many validations a serial has left is a fact about one person's purchase, not about the product. A recipe shared with strangers must not carry it. You record it yourself, as below.

## Recording what an environment holds

The recipe covers what is true of the vendor. Use this command for what the recipe cannot know, such as a serial with a fixed number of validations or a vendor with no recipe yet. Run it once the activations are in place.

~~~sh
plugg licensing protect \
  --environment ~/.local/share/plugg/environments/<id> \
  --product "Skaka:reactivatable" \
  --product "SpaceBlender:deactivate-first" \
  --product "ExampleSynth:limited-activations:3"
~~~

This writes `licensing.json` beside the prefix. It holds the product list and a baseline of the identity values a vendor reads to decide which computer this is.

**The record holds no secrets.** Plugg stores identity values as keyed hashes, never in the clear. The random per-environment key lives in a separate `.licensing-key` file with owner-only permissions. Several of the values are short and structured, so anyone could recover them from an unkeyed hash by guessing. With the key held back, you can attach `licensing.json` to a bug report without exposing your machine identifiers. Keep the key file and the recovery points to yourself. Plugg never collects serial numbers, credentials, licence files or account data. They stay in the vendor's own manager, as on any other computer. Do not paste licence details into a product name or note. Both have a length cap to discourage it.

To add products later, run the command again. Plugg merges them by name and re-reads the baseline:

~~~sh
plugg licensing protect --environment <path> --product "soothe:deactivate-first"
~~~

## One computer, one machine

Wine generates a fresh `MachineGuid` for every prefix it creates. Left alone, a computer with six managed environments would look like **six different machines** to any vendor that fingerprints on that value. Licences are sold per machine, so each environment would quietly use up an allowance, although they all run on one computer. One person on one computer could use up a vendor's "three machines" limit.

Plugg therefore gives each new environment this computer's machine identity when it creates the environment, before any vendor component runs. Plugg derives the value by hashing the host's own `machine-id`. The result is the same for every environment on the computer and stays stable across libraries and reinstalls, and Windows software never sees the host identifier itself. Plugg writes the value through Wine's own registry tooling, not by editing the hive.

Plugg never re-identifies an existing environment. Changing the value in an environment that already holds activations is exactly what makes a vendor see a different machine, so the guard refuses it. The feature sets the identity of new environments only. It does not rewrite existing ones. An environment created before this feature keeps the identity its licences were issued to. `licensing status` reports `machine_identity_is_this_computer: false` for those.

This has two limits. First, it handles the obvious fingerprint, not every one. PACE and similar schemes read much more than `MachineGuid`, so a fresh prefix may still look distinct to them. Second, each environment still has its own prefix creation date, which any software that checks can read.

If you do this at any scale, tell the vendor. A tool that makes one computer look like one computer is easy to explain up front, and harder to explain after the vendor finds it on their own.

## What the guard does

| Operation class | Examples | On a protected environment |
| --- | --- | --- |
| Read-only | scan, publish, launch, open helper | Always allowed. |
| In place | configure graphics, install a component, import a module | Allowed while the environment still matches its recorded identity. Refused once it does not, because something already changed. |
| Identity changing | create, recreate, reset, move or remove the prefix, replace the runtime | Refused. Requires an explicit acknowledgement. |

The guard refuses an unknown operation name. It fails closed.

`recipe apply` calls the guard before it takes any lock or writes any file, and records the outcome in `recipe-lock.json`. `recipe status` and the manager's installation details show the same result. They also warn when an environment no longer matches its record.

## Acknowledging a change you want

~~~sh
plugg licensing status --environment <path>
~~~

Read what it protects. Deactivate the products that need it, in their own manager. Then record that you did:

~~~sh
plugg licensing acknowledge --environment <path> \
  --operation recreate_prefix --confirm "I HAVE DEACTIVATED THIS ENVIRONMENT"
~~~

The phrase depends on the strictest product in the environment. Run the command without `--confirm` to see the phrase it needs. An acknowledgement covers one named operation and expires after two hours. The guard uses it up the first time it accepts it, so it authorizes the attempt you thought about, not every repeat within the window. Nothing creates an acknowledgement on your behalf.

For an environment with limited activations, the phrase is `I ACCEPT LOSING A LIMITED ACTIVATION`, because that is what will happen.

## Recovery points

~~~sh
plugg licensing backup --environment <path> --label before-runtime-change
plugg licensing backups --environment <path>
plugg licensing restore --environment <path> \
  --recovery-point 20260912T104500Z-before-runtime-change --confirm "<phrase>"
~~~

A recovery point copies only the identity files, meaning the registry hives, the runtime version and the runtime markers. It is small enough to take before every risky change. Unlike `licensing.json`, a recovery point is **not** shareable. Its registry copies contain your machine's identifiers in the clear, and so does the key file beside the record. Restore refuses to run while plug-ins from the environment are running. It checks every file against the manifest and first takes a fresh recovery point of the current state, so you can reverse a restore too.

This is a way back from an identity change. It is **not** a backup of installed products, activation payloads or user data, and it is not a filesystem snapshot.

## What this does not prove

- A matching record does not prove that a product is still authorized. It only means that the values this project can observe have not changed.
- Vendors may read host details outside the prefix, such as network hardware or host disks. This project cannot see or protect those.
- The guard covers operations that go through this manager. Editing a prefix by hand, or with other tools, bypasses it.
- Protection is per environment. It says nothing about a vendor's own server-side activation counting.

## For contributors

A recipe may not create, recreate or relocate a licensed environment, and may not carry a shell command that would. Anything that provisions PACE or joins an existing licensed environment stays out of the generic recipe path. See [the PACE recipe notes](recipes/pace.md) and [extension boundaries](recipe-authoring.md).

When you add an operation that writes inside a prefix, classify it in `plugg/licensing.py` and call `licensing.guard` before the first write. The guard refuses unclassified operations on purpose. A new operation should have to state what it does to a licensed machine.

## Recording a deactivation

When you deactivate a product with its vendor (for iLok products, in iLok License Manager), record it in the environment:

```sh
plugg licensing deactivated --environment <dir> --product "Softube Saturation Knob"
```

It prints the exact phrase to repeat with `--confirm`. The product moves from the environment's list to its history, with the date. When no products are left, the environment is no longer protected and you can rebuild it. Its identity record and recovery points stay. This project never checks activation state itself, so the record is only as current as what you tell it. The app's iLok card lists the plug-ins *installed* in the environment, not activations.
