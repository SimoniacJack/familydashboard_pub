# Family member profiles

One markdown file per person. The meal planner reads them to steer suggestions
(likes, dislikes, dietary needs, portion size).

## Setting up your family

1. Copy an `example-*.md` file to `<name>.md` for each member, e.g. `alex.md`.
2. Edit the likes / dislikes / dietary notes.
3. Optionally add a photo `<Name>.png` (shown in the UI).
4. Add each member in the app (or via the seed import) so the name matches.

Your real `<name>.md` files and photos are **gitignored** — they stay on your
own instance and are never committed. Only the `example-*.md` templates and this
README are tracked, so the public repo carries no real family's data.
