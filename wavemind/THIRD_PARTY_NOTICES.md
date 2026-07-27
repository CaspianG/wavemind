# Third-Party Notices

## OpenShape

WaveMind's optional local 3D encoder includes an inference-only adaptation of
the OpenShape PointBERT reference implementation.

- Project: OpenShape
- Source: https://github.com/Colin97/OpenShape_code
- Reference-code license: Apache License 2.0
- On-demand checkpoint: `OpenShape/openshape-pointbert-vitb32-rgb`
- Checkpoint license declared by its model card: MIT

The adaptation removes training-only dependencies, pins the model revision,
and uses deterministic point sampling. The Apache License 2.0 text is included
in `licenses/OpenShape-APACHE-2.0.txt`.
