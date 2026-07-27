"""Minimal OpenShape PointBERT inference runtime.

Adapted from OpenShape's Apache-2.0 reference implementation:
https://github.com/Colin97/OpenShape_code

Changes: removed training-only modules and third-party DGL/torch-redstone
dependencies, made farthest-point sampling deterministic, and restricted the
loader to the pinned CLIP ViT-B/32-aligned inference checkpoint.
"""

from __future__ import annotations

from typing import Any


OPENSHAPE_MODEL_NAME = "OpenShape/openshape-pointbert-vitb32-rgb"
OPENSHAPE_MODEL_REVISION = "47e04daac585b2ce1cbbc72a42c0bf11971acddd"
OPENSHAPE_VECTOR_DIM = 512


def load_openshape_pointbert(
    *,
    cache_folder: str | None = None,
    local_files_only: bool = False,
) -> Any:
    try:
        import torch
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            "OpenShape 3D encoding requires torch and huggingface-hub."
        ) from exc

    checkpoint = hf_hub_download(
        repo_id=OPENSHAPE_MODEL_NAME,
        filename="model.pt",
        revision=OPENSHAPE_MODEL_REVISION,
        cache_dir=cache_folder,
        local_files_only=local_files_only,
    )
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = _point_patch_transformer()
    weights = {
        ".".join(key.split(".")[1:]): value
        for key, value in state.items()
        if key.startswith("pc_encoder.")
    }
    model.load_state_dict(weights)
    model.eval()
    if torch.cuda.is_available():
        model.cuda()
    return model


def _point_patch_transformer() -> Any:
    import torch
    import torch.nn as nn

    class PointNetSetAbstraction(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.npoint = 64
            self.radius = 0.4
            self.nsample = 256
            # OpenShape's RGB checkpoint passes the complete XYZ+RGB feature
            # vector alongside the relative XYZ coordinates.
            channels = (9, 64, 64, 128)
            self.mlp_convs = nn.ModuleList(
                nn.Conv2d(channels[index], channels[index + 1], 1)
                for index in range(len(channels) - 1)
            )
            self.mlp_bns = nn.ModuleList(
                nn.BatchNorm2d(channel) for channel in channels[1:]
            )

        def forward(self, xyz: Any, points: Any) -> tuple[Any, Any]:
            xyz_rows = xyz.permute(0, 2, 1)
            point_rows = points.permute(0, 2, 1)
            sample_ids = _farthest_point_sample(xyz_rows, self.npoint)
            centroids = _index_points(xyz_rows, sample_ids)
            group_ids = _query_ball_point(
                self.radius,
                self.nsample,
                xyz_rows,
                centroids,
            )
            grouped_xyz = _index_points(xyz_rows, group_ids)
            grouped_points = _index_points(point_rows, group_ids)
            grouped = torch.cat(
                (
                    grouped_xyz - centroids.unsqueeze(2),
                    grouped_points,
                ),
                dim=-1,
            ).permute(0, 3, 2, 1)
            for conv, bn in zip(self.mlp_convs, self.mlp_bns, strict=True):
                grouped = torch.nn.functional.relu(bn(conv(grouped)))
            return centroids.permute(0, 2, 1), torch.max(grouped, 2)[0]

    class PreNorm(nn.Module):
        def __init__(self, dim: int, layer: Any) -> None:
            super().__init__()
            self.norm = nn.LayerNorm(dim)
            self.fn = layer

        def forward(self, value: Any, delta: Any) -> Any:
            return self.fn(self.norm(value), delta)

    class FeedForward(nn.Module):
        def __init__(self, dim: int, hidden_dim: int) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(0.0),
                nn.Linear(hidden_dim, dim),
                nn.Dropout(0.0),
            )

        def forward(self, value: Any, delta: Any = None) -> Any:
            del delta
            return self.net(value)

    class Attention(nn.Module):
        def __init__(self, dim: int, heads: int = 8, dim_head: int = 64) -> None:
            super().__init__()
            self.heads = heads
            self.scale = dim_head**-0.5
            inner_dim = dim_head * heads
            self.to_qkv = nn.Linear(dim, inner_dim * 3, bias=False)
            self.to_out = nn.Sequential(nn.Linear(inner_dim, dim), nn.Dropout(0.0))

        def forward(self, value: Any, delta: Any) -> Any:
            del delta
            batch, rows, _ = value.shape
            query, key, values = self.to_qkv(value).chunk(3, dim=-1)

            def split_heads(selected: Any) -> Any:
                return selected.reshape(batch, rows, self.heads, -1).permute(
                    0,
                    2,
                    1,
                    3,
                )

            query, key, values = (
                split_heads(query),
                split_heads(key),
                split_heads(values),
            )
            weights = torch.softmax(
                torch.matmul(query, key.transpose(-1, -2)) * self.scale,
                dim=-1,
            )
            attended = torch.matmul(weights, values).permute(0, 2, 1, 3)
            return self.to_out(attended.reshape(batch, rows, -1))

    class Transformer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = nn.ModuleList(
                nn.ModuleList(
                    (
                        PreNorm(512, Attention(512)),
                        PreNorm(512, FeedForward(512, 1024)),
                    )
                )
                for _ in range(12)
            )

        def forward(self, value: Any, delta: Any) -> Any:
            for attention, feed_forward in self.layers:
                value = attention(value, delta) + value
                value = feed_forward(value, delta) + value
            return value

    class PointPatchTransformer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.sa = PointNetSetAbstraction()
            self.lift = nn.Sequential(
                nn.Conv1d(131, 512, 1),
                _Permute(),
                nn.LayerNorm([512]),
            )
            self.cls_token = nn.Parameter(torch.randn(512))
            self.transformer = Transformer()

        def forward(self, features: Any) -> Any:
            centroids, feature = self.sa(features[:, :3], features)
            value = self.lift(torch.cat((centroids, feature), dim=1))
            token = self.cls_token.view(1, 1, -1).expand(value.shape[0], 1, -1)
            value = torch.cat((token, value), dim=1)
            zero = centroids.new_zeros((centroids.shape[0], 3, 1))
            centroids = torch.cat((zero, centroids), dim=-1)
            delta = centroids.unsqueeze(-1) - centroids.unsqueeze(-2)
            return self.transformer(value, delta)[:, 0]

    class _Permute(nn.Module):
        def forward(self, value: Any) -> Any:
            return value.permute(0, 2, 1)

    return PointPatchTransformer()


def _square_distance(source: Any, destination: Any) -> Any:
    import torch

    distance = -2 * torch.matmul(source, destination.permute(0, 2, 1))
    distance += torch.sum(source**2, -1).unsqueeze(-1)
    distance += torch.sum(destination**2, -1).unsqueeze(1)
    return distance


def _index_points(points: Any, indexes: Any) -> Any:
    import torch

    batch = points.shape[0]
    view_shape = list(indexes.shape)
    view_shape[1:] = [1] * (len(view_shape) - 1)
    repeat_shape = list(indexes.shape)
    repeat_shape[0] = 1
    batch_indexes = (
        torch.arange(batch, dtype=torch.long, device=points.device)
        .view(view_shape)
        .repeat(repeat_shape)
    )
    return points[batch_indexes, indexes, :]


def _farthest_point_sample(points: Any, count: int) -> Any:
    import torch

    batch, rows, channels = points.shape
    centroids = torch.zeros(batch, count, dtype=torch.long, device=points.device)
    distance = torch.full((batch, rows), 1e10, device=points.device)
    farthest = torch.zeros(batch, dtype=torch.long, device=points.device)
    batch_indexes = torch.arange(batch, device=points.device)
    for index in range(count):
        centroids[:, index] = farthest
        centroid = points[batch_indexes, farthest, :].view(batch, 1, channels)
        candidate = torch.sum((points - centroid) ** 2, -1)
        distance = torch.minimum(distance, candidate)
        farthest = torch.max(distance, -1).indices
    return centroids


def _query_ball_point(
    radius: float,
    sample_count: int,
    points: Any,
    centroids: Any,
) -> Any:
    import torch

    batch, rows, _ = points.shape
    centroid_count = centroids.shape[1]
    indexes = (
        torch.arange(rows, dtype=torch.long, device=points.device)
        .view(1, 1, rows)
        .repeat(batch, centroid_count, 1)
    )
    indexes[_square_distance(centroids, points) > radius**2] = rows
    indexes = indexes.sort(dim=-1)[0][:, :, :sample_count]
    first = indexes[..., :1].repeat(1, 1, sample_count)
    indexes[indexes == rows] = first[indexes == rows]
    return indexes
