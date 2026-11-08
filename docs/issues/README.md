# Issue drafts

Open questions and tasks from the planning log, to be filed as GitHub issues once the
repository exists. Each file has `title` and `labels` frontmatter. After filing, delete
this directory.

```sh
gh auth login
for l in question decision-needed task footage video studio schema pipeline packaging licensing; do
    gh label create "$l" --force
done
for f in docs/issues/[0-9]*.md; do
    title=$(sed -n 's/^title: //p' "$f" | head -1)
    labels=$(sed -n 's/^labels: //p' "$f" | head -1)
    awk 'n >= 2; /^---$/ { n++ }' "$f" | gh issue create --title "$title" --label "$labels" --body-file -
done
```
