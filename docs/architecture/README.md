# RoboClaws architecture diagram demo

This directory is a prototype for a maintainable architecture-document workflow.

## Source of truth

`roboclaws-overview.d2` is the editable source. `roboclaws-overview.svg` is the checked-in publication artifact used by the README. Render it locally after changing the D2 source:

```sh
d2 \
  --layout=elk \
  --elk-nodeNodeBetweenLayers=10 \
  --elk-edgeNodeBetweenLayers=10 \
  --elk-padding='[top=20,left=20,bottom=20,right=20]' \
  --pad=20 \
  docs/architecture/roboclaws-overview.d2 \
  docs/architecture/roboclaws-overview.svg
```

The ELK spacing and outer padding are kept explicit so repeated local renders stay compact and deterministic. The design intentionally uses a restrained engineering-doc vocabulary: white canvas, dark typography, one pastel surface per semantic layer, and a top-to-bottom flow connecting two compact horizontal planes.

## Fallback visual reference

The image-generation concept used to establish the visual direction is not included in this draft. The intended fallback filename is `roboclaws-overview-concept.png`; if added later, it will be a design reference/visual benchmark, not the architecture source of truth.

The repository does not render or rewrite this artifact in CI. Commit the regenerated SVG with source changes so README remains a static, reviewable document. Keep any concept PNG only as a visual benchmark while this experiment is evaluated.
