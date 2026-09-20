## What this changes

<!-- One or two sentences. Vendor recipes aren't taken by pull request yet; see CONTRIBUTING. For a shared component, say which vendors need it. -->

## Evidence

<!-- Delete the sections that do not apply. Claims without evidence are the thing this project is trying to avoid, so "it works for me" is not enough. -->

**For a recipe or compatibility change**, state separately what you observed:

- [ ] Installation completed
- [ ] Authorization completed
- [ ] Audio processes correctly
- [ ] Editor opens
- [ ] Editor closes and reopens
- [ ] Multiple instances
- [ ] Project saved and recalled

Exact product and installer versions, runtime and bridge identity, distribution, graphics driver, desktop and DAW version:

```
```

**For code**, which checks did you run?

- [ ] `python3 scripts/check-contribution.py`
- [ ] Something that exercises the change specifically (say what)

## Safety

- [ ] I did not include installers, licence files, account data, callback URLs, prefixes or downloaded runtimes.
- [ ] I did not copy an activated prefix into a fixture.
- [ ] If this adds an operation that writes inside a Windows environment, it is classified in `plugg/licensing.py` and calls `licensing.guard`.
- [ ] If this adds a recipe, I have read its report: `python3 scripts/review-recipe.py <my recipe>`

<!-- CI posts that same report on this pull request. A recipe that declares more than its directory allows is refused automatically; moving it to recipes/reviewed/ requires a maintainer, not a different commit message. -->
