from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from wavemind.multimodal_public_benchmark import (
    PUBLIC_MULTIMODAL_SUITE_SCHEMA,
    load_public_multimodal_suite,
)
from wavemind.object_store import S3AssetStore


SUITE_REVISION = "wavemind-public-multimodal-v1"
CIFAR_REVISION = "aadb3af77e9048adbea6b47c21a81e47dd092ae5"
ESC50_REVISION = "825dcaabaddcaa0836ad79ed115d256db6e7ed76"
UCF101_REVISION = "057753e5d0709d3f5b8104a803b91a420a069103"
MODELNET40_REVISION = "aeb0af95f3ddc6503b5613c28ebcece569e3c2e2"
MODELNET40_REPO = "naderalfares/ModelNet40_Auto_aligned"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

CIFAR_LABELS = (
    "apple",
    "aquarium_fish",
    "baby",
    "bear",
    "beaver",
    "bed",
    "bee",
    "beetle",
    "bicycle",
    "bottle",
    "bowl",
    "boy",
    "bridge",
    "bus",
    "butterfly",
    "camel",
    "can",
    "castle",
    "caterpillar",
    "cattle",
    "chair",
    "chimpanzee",
    "clock",
    "cloud",
    "cockroach",
    "couch",
    "crab",
    "crocodile",
    "cup",
    "dinosaur",
    "dolphin",
    "elephant",
    "flatfish",
    "forest",
    "fox",
    "girl",
    "hamster",
    "house",
    "kangaroo",
    "keyboard",
    "lamp",
    "lawn_mower",
    "leopard",
    "lion",
    "lizard",
    "lobster",
    "man",
    "maple_tree",
    "motorcycle",
    "mountain",
    "mouse",
    "mushroom",
    "oak_tree",
    "orange",
    "orchid",
    "otter",
    "palm_tree",
    "pear",
    "pickup_truck",
    "pine_tree",
    "plain",
    "plate",
    "poppy",
    "porcupine",
    "possum",
    "rabbit",
    "raccoon",
    "ray",
    "road",
    "rocket",
    "rose",
    "sea",
    "seal",
    "shark",
    "shrew",
    "skunk",
    "skyscraper",
    "snail",
    "snake",
    "spider",
    "squirrel",
    "streetcar",
    "sunflower",
    "sweet_pepper",
    "table",
    "tank",
    "telephone",
    "television",
    "tiger",
    "tractor",
    "train",
    "trout",
    "tulip",
    "turtle",
    "wardrobe",
    "whale",
    "willow_tree",
    "wolf",
    "woman",
    "worm",
)

ESC50_LABELS = (
    "dog",
    "rooster",
    "pig",
    "cow",
    "frog",
    "cat",
    "hen",
    "insects",
    "sheep",
    "crow",
    "rain",
    "sea_waves",
    "crackling_fire",
    "crickets",
    "chirping_birds",
    "water_drops",
    "wind",
    "pouring_water",
    "toilet_flush",
    "thunderstorm",
    "crying_baby",
    "sneezing",
    "clapping",
    "breathing",
    "coughing",
    "footsteps",
    "laughing",
    "brushing_teeth",
    "snoring",
    "drinking_sipping",
    "door_wood_knock",
    "mouse_click",
    "keyboard_typing",
    "door_wood_creaks",
    "can_opening",
    "washing_machine",
    "vacuum_cleaner",
    "clock_alarm",
    "clock_tick",
    "glass_breaking",
    "helicopter",
    "chainsaw",
    "siren",
    "car_horn",
    "engine",
    "train",
    "church_bells",
    "airplane",
    "fireworks",
    "hand_saw",
)

IMAGE_CONCEPTS = (
    "bear",
    "bicycle",
    "bridge",
    "bus",
    "butterfly",
    "camel",
    "dolphin",
    "elephant",
    "forest",
    "motorcycle",
    "mountain",
    "rocket",
    "sunflower",
    "tiger",
    "apple",
    "television",
    "turtle",
    "whale",
    "skyscraper",
    "tractor",
)

AUDIO_CONCEPTS = (
    "dog",
    "rooster",
    "rain",
    "sea_waves",
    "crackling_fire",
    "thunderstorm",
    "crying_baby",
    "sneezing",
    "clapping",
    "coughing",
    "footsteps",
    "laughing",
    "door_wood_knock",
    "can_opening",
    "vacuum_cleaner",
    "clock_alarm",
    "helicopter",
    "siren",
    "fireworks",
    "chainsaw",
)

VIDEO_CONCEPTS = (
    "Archery",
    "BabyCrawling",
    "BasketballDunk",
    "Biking",
    "BlowDryHair",
    "Bowling",
    "BoxingPunchingBag",
    "BrushingTeeth",
    "CliffDiving",
    "Drumming",
    "Fencing",
    "HorseRiding",
    "JumpRope",
    "Kayaking",
    "Knitting",
    "PlayingGuitar",
    "PlayingPiano",
    "PushUps",
    "Skiing",
    "Typing",
)

MODELNET_CONCEPTS = (
    "airplane",
    "bathtub",
    "bed",
    "bench",
    "bookshelf",
    "bottle",
    "bowl",
    "car",
    "chair",
    "cone",
    "cup",
    "desk",
    "door",
    "dresser",
    "flower_pot",
    "lamp",
    "laptop",
    "mantel",
    "sofa",
    "toilet",
)

WIKI_TITLE_OVERRIDES = {
    "baby_crawling": "Crawling (human)",
    "basketball_dunk": "Slam dunk",
    "biking": "Cycling",
    "blow_dry_hair": "Hair dryer",
    "boxing_punching_bag": "Punching bag",
    "brushing_teeth": "Tooth brushing",
    "can_opening": "Can opener",
    "clock_alarm": "Alarm clock",
    "crackling_fire": "Fire",
    "crying_baby": "Infant crying",
    "door_wood_knock": "Knocking",
    "flower_pot": "Flowerpot",
    "horse_riding": "Equestrianism",
    "jump_rope": "Skipping rope",
    "lamp": "Light fixture",
    "playing_guitar": "Guitar",
    "playing_piano": "Piano",
    "push_ups": "Push-up",
    "sea_waves": "Wind wave",
    "vacuum_cleaner": "Vacuum cleaner",
}


@dataclass(frozen=True)
class SourceSample:
    dataset_id: str
    modality: str
    concept: str
    source_ref: str
    source_url: str
    media_type: str
    suffix: str
    content: bytes


@dataclass(frozen=True)
class WikipediaDocument:
    concept: str
    title: str
    revision: str
    timestamp: str
    source_url: str
    text: str


@dataclass(frozen=True)
class UploadResult:
    uri: str
    verified: bool


class AssetUploader(Protocol):
    def upload(self, path: Path, *, modality: str, asset_id: str) -> UploadResult: ...


class MinioAssetUploader:
    def __init__(self, store: S3AssetStore):
        self.store = store

    def upload(self, path: Path, *, modality: str, asset_id: str) -> UploadResult:
        report = self.store.upload_asset(
            path,
            media_type=_media_type(path),
            kind=modality,
            key=f"{SUITE_REVISION}/{modality}/{path.name}",
            source_uri=path.resolve().as_uri(),
            verify=True,
        )
        if not report.verified:
            raise RuntimeError(f"object verification failed for {path}")
        return UploadResult(uri=report.uri, verified=True)


def prepare_public_multimodal_suite(
    *,
    output_dir: str | Path,
    samples: Mapping[str, Mapping[str, Sequence[SourceSample]]],
    wikipedia_documents: Mapping[str, WikipediaDocument],
    uploader: AssetUploader,
    stored_per_concept: int = 10,
    text_asset_total: int = 200,
    mixed_queries_per_pair: int = 20,
    suite_revision: str = SUITE_REVISION,
    dataset_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> Path:
    root = Path(output_dir).resolve()
    assets_root = root / "assets"
    queries_root = root / "queries"
    assets_root.mkdir(parents=True, exist_ok=True)
    queries_root.mkdir(parents=True, exist_ok=True)
    if stored_per_concept < 1:
        raise ValueError("stored_per_concept must be positive")

    modality_concepts = {
        modality: tuple(sorted(concept_rows))
        for modality, concept_rows in samples.items()
    }
    required_modalities = {"image", "audio", "video", "3d"}
    if set(modality_concepts) != required_modalities:
        raise ValueError(
            "samples must contain exactly image, audio, video, and 3d modalities"
        )
    all_concepts = [
        concept
        for modality in ("image", "audio", "video", "3d")
        for concept in modality_concepts[modality]
    ]
    if len(all_concepts) != len(set(all_concepts)):
        raise ValueError("concept names must be unique across media modalities")

    asset_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    asset_ids_by_concept: dict[tuple[str, str], list[str]] = defaultdict(list)
    held_out: dict[tuple[str, str], SourceSample] = {}

    for modality in ("image", "audio", "video", "3d"):
        for concept in modality_concepts[modality]:
            rows = sorted(
                samples[modality][concept],
                key=lambda item: item.source_ref,
            )
            if len(rows) < stored_per_concept + 1:
                raise ValueError(
                    f"{modality}/{concept} needs at least "
                    f"{stored_per_concept + 1} independent samples"
                )
            for index, sample in enumerate(rows[:stored_per_concept]):
                asset_id = _opaque_id(
                    "a",
                    suite_revision,
                    sample.dataset_id,
                    sample.modality,
                    sample.source_ref,
                    str(index),
                )
                path = assets_root / f"{asset_id}{sample.suffix}"
                path.write_bytes(sample.content)
                upload = uploader.upload(
                    path,
                    modality=modality,
                    asset_id=asset_id,
                )
                asset_rows.append(
                    _asset_row(
                        asset_id=asset_id,
                        modality=modality,
                        path=path,
                        root=root,
                        dataset_id=sample.dataset_id,
                        object_result=upload,
                    )
                )
                provenance_rows.append(
                    _provenance_row(
                        asset_id=asset_id,
                        concept=concept,
                        sample=sample,
                        role="stored",
                    )
                )
                asset_ids_by_concept[(modality, concept)].append(asset_id)
            held_out[(modality, concept)] = rows[stored_per_concept]

    text_counts = _balanced_text_counts(all_concepts, total=text_asset_total)
    for concept in all_concepts:
        document = wikipedia_documents.get(concept)
        if document is None:
            raise ValueError(f"missing Wikipedia document for concept {concept!r}")
        chunks = _wikipedia_chunks(document, count=text_counts[concept])
        for index, content in enumerate(chunks):
            source_ref = f"{document.revision}:{index}"
            asset_id = _opaque_id(
                "a",
                suite_revision,
                "wikipedia",
                "text",
                concept,
                source_ref,
            )
            path = assets_root / f"{asset_id}.txt"
            path.write_text(content, encoding="utf-8")
            upload = uploader.upload(path, modality="text", asset_id=asset_id)
            asset_rows.append(
                _asset_row(
                    asset_id=asset_id,
                    modality="text",
                    path=path,
                    root=root,
                    dataset_id="wikipedia",
                    object_result=upload,
                )
            )
            provenance_rows.append(
                {
                    "asset_id": asset_id,
                    "concept": concept,
                    "dataset_id": "wikipedia",
                    "role": "stored",
                    "source_ref": source_ref,
                    "source_url": document.source_url,
                    "source_revision": document.revision,
                    "source_timestamp": document.timestamp,
                    "content_sha256": _sha256(path),
                }
            )
            asset_ids_by_concept[("text", concept)].append(asset_id)

    queries: list[dict[str, Any]] = []
    relevant: dict[str, list[str]] = {}
    query_provenance: list[dict[str, Any]] = []
    query_counter = 0

    for modality in ("image", "audio", "video", "3d"):
        for concept in modality_concepts[modality]:
            query_counter += 1
            text_query = _human_query(concept, target_modality=modality)
            query_id = _opaque_id(
                "q",
                suite_revision,
                "text-to-media",
                modality,
                concept,
            )
            query_path = queries_root / f"{query_id}.txt"
            query_path.write_text(text_query, encoding="utf-8")
            queries.append(
                _query_row(
                    query_id,
                    ((query_path, "text", 1.0),),
                    root=root,
                    target_modalities=(modality,),
                )
            )
            relevant[query_id] = list(asset_ids_by_concept[(modality, concept)])
            query_provenance.append(
                {
                    "query_id": query_id,
                    "concept": concept,
                    "direction": f"text->{modality}",
                    "held_out": True,
                    "query_text_sha256": _sha256(query_path),
                }
            )

            query_counter += 1
            held = held_out[(modality, concept)]
            media_query_id = _opaque_id(
                "q",
                suite_revision,
                "media-to-text",
                modality,
                held.source_ref,
            )
            media_path = queries_root / f"{media_query_id}{held.suffix}"
            media_path.write_bytes(held.content)
            queries.append(
                _query_row(
                    media_query_id,
                    ((media_path, modality, 1.0),),
                    root=root,
                    target_modalities=("text",),
                )
            )
            relevant[media_query_id] = list(asset_ids_by_concept[("text", concept)])
            query_provenance.append(
                {
                    "query_id": media_query_id,
                    "concept": concept,
                    "direction": f"{modality}->text",
                    "held_out": True,
                    "source_ref": held.source_ref,
                    "source_url": held.source_url,
                    "content_sha256": _sha256(media_path),
                }
            )

    query_counter = _append_mixed_queries(
        queries=queries,
        relevant=relevant,
        provenance=query_provenance,
        counter=query_counter,
        root=root,
        queries_root=queries_root,
        suite_revision=suite_revision,
        pairs=(("image", "audio"), ("video", "3d")),
        modality_concepts=modality_concepts,
        held_out=held_out,
        asset_ids_by_concept=asset_ids_by_concept,
        queries_per_pair=mixed_queries_per_pair,
    )

    asset_rows.sort(key=lambda row: row["id"])
    queries.sort(key=lambda row: row["id"])
    provenance_rows.sort(key=lambda row: row["asset_id"])
    query_provenance.sort(key=lambda row: row["query_id"])
    ground_truth = {
        "relevant_asset_ids": {
            query_id: sorted(ids) for query_id, ids in sorted(relevant.items())
        }
    }

    assets_path = root / "assets.json"
    queries_path = root / "queries.json"
    ground_truth_path = root / "ground-truth.json"
    provenance_path = root / "provenance.json"
    _write_json(assets_path, asset_rows)
    _write_json(queries_path, queries)
    _write_json(ground_truth_path, ground_truth)
    _write_json(
        provenance_path,
        {
            "schema": "wavemind.public-multimodal-provenance.v1",
            "suite_revision": suite_revision,
            "assets": provenance_rows,
            "queries": query_provenance,
        },
    )

    metadata = list(dataset_metadata or _default_dataset_metadata())
    suite_path = root / "suite.json"
    _write_json(
        suite_path,
        {
            "schema": PUBLIC_MULTIMODAL_SUITE_SCHEMA,
            "name": "WaveMind Public Multimodal Retrieval Suite",
            "revision": suite_revision,
            "license": "mixed; see per-dataset license and terms",
            "datasets": metadata,
            "asset_manifest": assets_path.name,
            "asset_manifest_sha256": _sha256(assets_path),
            "query_manifest": queries_path.name,
            "query_manifest_sha256": _sha256(queries_path),
            "ground_truth": ground_truth_path.name,
            "ground_truth_sha256": _sha256(ground_truth_path),
            "provenance_manifest": provenance_path.name,
            "provenance_manifest_sha256": _sha256(provenance_path),
            "counts": {
                "assets": len(asset_rows),
                "queries": len(queries),
                "query_parts": sum(len(row["parts"]) for row in queries),
                "assets_by_modality": _counts(asset_rows, "modality"),
                "query_parts_by_modality": _query_part_counts(queries),
                "direct_cross_modal_queries": len(all_concepts) * 2,
                "mixed_queries": mixed_queries_per_pair * 2,
            },
        },
    )
    loaded = load_public_multimodal_suite(suite_path)
    if len(loaded.assets) != len(asset_rows) or len(loaded.queries) != len(queries):
        raise RuntimeError("written suite did not round-trip through strict loader")
    return suite_path


def load_cifar_samples(
    parquet_path: str | Path,
    *,
    concepts: Sequence[str] = IMAGE_CONCEPTS,
) -> dict[str, list[SourceSample]]:
    table = _read_parquet(parquet_path)
    wanted = set(concepts)
    result: dict[str, list[SourceSample]] = defaultdict(list)
    for index, row in enumerate(table.to_pylist()):
        concept = CIFAR_LABELS[int(row["fine_label"])]
        if concept not in wanted:
            continue
        image = row["img"]
        content = bytes(image["bytes"])
        result[concept].append(
            SourceSample(
                dataset_id="cifar100",
                modality="image",
                concept=concept,
                source_ref=f"test:{index}",
                source_url=(
                    "https://huggingface.co/datasets/uoft-cs/cifar100/"
                    f"tree/{CIFAR_REVISION}"
                ),
                media_type="image/png",
                suffix=".png",
                content=content,
            )
        )
    return _require_concepts(result, concepts, minimum=11, dataset="CIFAR-100")


def load_esc50_samples(
    parquet_paths: Sequence[str | Path],
    *,
    concepts: Sequence[str] = AUDIO_CONCEPTS,
) -> dict[str, list[SourceSample]]:
    wanted = set(concepts)
    result: dict[str, list[SourceSample]] = defaultdict(list)
    global_index = 0
    for parquet_path in sorted(Path(path) for path in parquet_paths):
        table = _read_parquet(parquet_path)
        for row in table.to_pylist():
            concept = ESC50_LABELS[int(row["label"])]
            if concept in wanted:
                audio = row["audio"]
                content = bytes(audio["bytes"])
                result[concept].append(
                    SourceSample(
                        dataset_id="esc50",
                        modality="audio",
                        concept=concept,
                        source_ref=f"{row['src_file']}:{global_index}",
                        source_url=(
                            "https://huggingface.co/datasets/renumics/esc50/"
                            f"tree/{ESC50_REVISION}"
                        ),
                        media_type="audio/wav",
                        suffix=".wav",
                        content=content,
                    )
                )
            global_index += 1
    return _require_concepts(result, concepts, minimum=11, dataset="ESC-50")


def load_ucf101_samples(
    tar_paths: Sequence[str | Path],
    *,
    concepts: Sequence[str] = VIDEO_CONCEPTS,
) -> dict[str, list[SourceSample]]:
    wanted = set(concepts)
    references: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for tar_path in sorted(Path(path) for path in tar_paths):
        with tarfile.open(tar_path, mode="r") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if len(parts) != 3 or parts[0] != "video":
                    continue
                concept = parts[1]
                if concept in wanted and member.isfile():
                    references[concept].append((tar_path, member.name))
    _require_concepts(references, concepts, minimum=11, dataset="UCF101")
    result: dict[str, list[SourceSample]] = defaultdict(list)
    grouped_by_tar: dict[Path, list[tuple[str, str]]] = defaultdict(list)
    for concept in concepts:
        selected = sorted(references[concept], key=lambda item: item[1])[:11]
        for tar_path, member_name in selected:
            grouped_by_tar[tar_path].append((concept, member_name))
    for tar_path, selected in grouped_by_tar.items():
        with tarfile.open(tar_path, mode="r") as archive:
            for concept, member_name in selected:
                extracted = archive.extractfile(member_name)
                if extracted is None:
                    raise RuntimeError(f"unable to read UCF101 member {member_name}")
                result[concept].append(
                    SourceSample(
                        dataset_id="ucf101",
                        modality="video",
                        concept=_concept_key(concept),
                        source_ref=member_name,
                        source_url=(
                            "https://huggingface.co/datasets/guyuchao/UCF101/"
                            f"tree/{UCF101_REVISION}"
                        ),
                        media_type="video/mp4",
                        suffix=".mp4",
                        content=extracted.read(),
                    )
                )
    keyed = {_concept_key(key): value for key, value in result.items()}
    expected = tuple(_concept_key(value) for value in concepts)
    return _require_concepts(keyed, expected, minimum=11, dataset="UCF101")


def download_modelnet40_subset(
    destination: str | Path,
    *,
    concepts: Sequence[str] = MODELNET_CONCEPTS,
    files_per_concept: int = 11,
) -> Path:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            'Install multimodal dependencies with: pip install -e ".[multimodal]"'
        ) from exc
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    files = api.list_repo_files(
        MODELNET40_REPO,
        repo_type="dataset",
        revision=MODELNET40_REVISION,
    )
    for concept in concepts:
        prefix = f"{concept}/test/"
        selected = sorted(
            path for path in files if path.startswith(prefix) and path.endswith(".off")
        )[:files_per_concept]
        if len(selected) < files_per_concept:
            raise ValueError(
                f"ModelNet40 concept {concept!r} has only {len(selected)} test files"
            )
        for filename in selected:
            downloaded = Path(
                hf_hub_download(
                    repo_id=MODELNET40_REPO,
                    filename=filename,
                    repo_type="dataset",
                    revision=MODELNET40_REVISION,
                    local_dir=root,
                )
            )
            if not downloaded.is_file():
                raise RuntimeError(f"ModelNet40 download missing: {downloaded}")
    return root


def load_modelnet40_samples(
    root: str | Path,
    *,
    concepts: Sequence[str] = MODELNET_CONCEPTS,
) -> dict[str, list[SourceSample]]:
    root_path = Path(root).resolve()
    result: dict[str, list[SourceSample]] = defaultdict(list)
    for concept in concepts:
        files = sorted((root_path / concept / "test").glob("*.off"))
        for path in files:
            result[concept].append(
                SourceSample(
                    dataset_id="modelnet40",
                    modality="3d",
                    concept=concept,
                    source_ref=path.relative_to(root_path).as_posix(),
                    source_url=(
                        "https://huggingface.co/datasets/"
                        f"{MODELNET40_REPO}/tree/{MODELNET40_REVISION}"
                    ),
                    media_type="model/vnd.off",
                    suffix=".off",
                    content=path.read_bytes(),
                )
            )
    return _require_concepts(
        result,
        concepts,
        minimum=11,
        dataset="ModelNet40",
    )


def fetch_wikipedia_documents(
    concepts: Sequence[str],
    *,
    cache_path: str | Path,
    opener: Callable[..., Any] = urllib.request.urlopen,
    rate_limit_seconds: float = 0.5,
) -> dict[str, WikipediaDocument]:
    cache = Path(cache_path).resolve()
    documents: dict[str, WikipediaDocument] = {}
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        if payload.get("schema") != "wavemind.wikipedia-source-cache.v1":
            raise ValueError("invalid Wikipedia cache schema")
        documents = {
            row["concept"]: WikipediaDocument(**row)
            for row in payload.get("documents", [])
        }
        missing = set(concepts) - set(documents)
        if not missing:
            return {concept: documents[concept] for concept in concepts}

    missing_concepts = [concept for concept in concepts if concept not in documents]
    for offset in range(0, len(missing_concepts), 20):
        batch = missing_concepts[offset : offset + 20]
        titles = [_wikipedia_title(concept) for concept in batch]
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "extracts|revisions",
                "explaintext": "1",
                "exintro": "1",
                "exlimit": "max",
                "exsectionformat": "plain",
                "rvprop": "ids|timestamp",
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join(titles),
            }
        )
        request = urllib.request.Request(
            f"{WIKIPEDIA_API}?{query}",
            headers={"User-Agent": "WaveMindBenchmark/1.0 (CaspianG/wavemind)"},
        )
        payload = _read_json_with_retry(
            request,
            opener=opener,
            timeout=60,
        )
        pages = {
            _normalize_title(page["title"]): page
            for page in payload["query"]["pages"]
            if not page.get("missing")
        }
        aliases = {
            _normalize_title(row["from"]): _normalize_title(row["to"])
            for key in ("normalized", "redirects")
            for row in payload["query"].get(key, [])
        }
        for concept, title in zip(batch, titles, strict=True):
            resolved = _normalize_title(title)
            visited: set[str] = set()
            while resolved in aliases and resolved not in visited:
                visited.add(resolved)
                resolved = aliases[resolved]
            page = pages.get(resolved)
            if page is None or not str(page.get("extract") or "").strip():
                raise ValueError(f"Wikipedia page unavailable for {concept!r}: {title}")
            revision = page["revisions"][0]
            revid = str(revision["revid"])
            documents[concept] = WikipediaDocument(
                concept=concept,
                title=str(page["title"]),
                revision=revid,
                timestamp=str(revision["timestamp"]),
                source_url=(
                    "https://en.wikipedia.org/w/index.php?"
                    + urllib.parse.urlencode({"title": page["title"], "oldid": revid})
                ),
                text=str(page["extract"]).strip(),
            )
        _write_wikipedia_cache(cache, documents)
        if rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)
    return {concept: documents[concept] for concept in concepts}


def _read_json_with_retry(
    request: urllib.request.Request,
    *,
    opener: Callable[..., Any],
    timeout: float,
    attempts: int = 6,
) -> dict[str, Any]:
    for attempt in range(attempts):
        try:
            with opener(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt + 1 >= attempts:
                raise
            retry_after = float(exc.headers.get("Retry-After") or 0.0)
            time.sleep(max(retry_after, min(30.0, 2.0**attempt)))
    raise RuntimeError("unreachable Wikipedia retry state")


def _write_wikipedia_cache(
    cache: Path,
    documents: Mapping[str, WikipediaDocument],
) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        cache,
        {
            "schema": "wavemind.wikipedia-source-cache.v1",
            "documents": [
                document.__dict__
                for document in sorted(
                    documents.values(),
                    key=lambda item: item.concept,
                )
            ],
        },
    )


def _append_mixed_queries(
    *,
    queries: list[dict[str, Any]],
    relevant: dict[str, list[str]],
    provenance: list[dict[str, Any]],
    counter: int,
    root: Path,
    queries_root: Path,
    suite_revision: str,
    pairs: Sequence[tuple[str, str]],
    modality_concepts: Mapping[str, Sequence[str]],
    held_out: Mapping[tuple[str, str], SourceSample],
    asset_ids_by_concept: Mapping[tuple[str, str], Sequence[str]],
    queries_per_pair: int,
) -> int:
    for left, right in pairs:
        left_concepts = modality_concepts[left]
        right_concepts = modality_concepts[right]
        if queries_per_pair > min(len(left_concepts), len(right_concepts)):
            raise ValueError("mixed query count exceeds available independent concepts")
        for index in range(queries_per_pair):
            counter += 1
            left_concept = left_concepts[index]
            right_concept = right_concepts[index]
            left_sample = held_out[(left, left_concept)]
            right_sample = held_out[(right, right_concept)]
            query_id = _opaque_id(
                "q",
                suite_revision,
                "mixed",
                left,
                left_sample.source_ref,
                right,
                right_sample.source_ref,
            )
            left_path = queries_root / f"{query_id}{left_sample.suffix}"
            right_path = queries_root / f"{query_id}{right_sample.suffix}"
            left_path.write_bytes(left_sample.content)
            right_path.write_bytes(right_sample.content)
            queries.append(
                _query_row(
                    query_id,
                    (
                        (left_path, left, 1.0),
                        (right_path, right, 1.0),
                    ),
                    root=root,
                    target_modalities=(left, right),
                )
            )
            relevant[query_id] = [
                *asset_ids_by_concept[(left, left_concept)],
                *asset_ids_by_concept[(right, right_concept)],
            ]
            provenance.append(
                {
                    "query_id": query_id,
                    "concepts": [left_concept, right_concept],
                    "direction": f"mixed:{left}+{right}",
                    "held_out": True,
                    "source_refs": [
                        left_sample.source_ref,
                        right_sample.source_ref,
                    ],
                    "content_sha256": [
                        _sha256(left_path),
                        _sha256(right_path),
                    ],
                }
            )
    return counter


def _asset_row(
    *,
    asset_id: str,
    modality: str,
    path: Path,
    root: Path,
    dataset_id: str,
    object_result: UploadResult,
) -> dict[str, Any]:
    if not object_result.verified:
        raise RuntimeError(f"asset {asset_id} was not verified in object storage")
    return {
        "id": asset_id,
        "modality": modality,
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "media_type": _media_type(path),
        "dataset_id": dataset_id,
        "object_uri": object_result.uri,
        "object_verified": True,
    }


def _query_row(
    query_id: str,
    parts: Sequence[tuple[Path, str, float]],
    *,
    root: Path,
    target_modalities: Sequence[str],
) -> dict[str, Any]:
    return {
        "id": query_id,
        "parts": [
            {
                "modality": modality,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "weight": weight,
            }
            for path, modality, weight in parts
        ],
        "target_modalities": list(target_modalities),
    }


def _provenance_row(
    *,
    asset_id: str,
    concept: str,
    sample: SourceSample,
    role: str,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "concept": concept,
        "dataset_id": sample.dataset_id,
        "role": role,
        "source_ref": sample.source_ref,
        "source_url": sample.source_url,
        "content_sha256": hashlib.sha256(sample.content).hexdigest(),
    }


def _balanced_text_counts(
    concepts: Sequence[str],
    *,
    total: int,
) -> dict[str, int]:
    if not concepts or total < len(concepts):
        raise ValueError("text asset total must cover every concept")
    base, extra = divmod(total, len(concepts))
    return {
        concept: base + (1 if index < extra else 0)
        for index, concept in enumerate(concepts)
    }


def _wikipedia_chunks(
    document: WikipediaDocument,
    *,
    count: int,
) -> list[str]:
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", document.text)
        if len(re.sub(r"\s+", " ", paragraph).strip()) >= 120
    ]
    if len(paragraphs) < count:
        words = re.sub(r"\s+", " ", document.text).split()
        chunk_size = max(20, len(words) // count)
        paragraphs = [
            " ".join(
                words[
                    index * chunk_size : (index + 1) * chunk_size
                    if index + 1 < count
                    else len(words)
                ]
            )
            for index in range(count)
            if len(
                words[
                    index * chunk_size : (index + 1) * chunk_size
                    if index + 1 < count
                    else len(words)
                ]
            )
            >= 20
        ]
    if len(paragraphs) < count:
        raise ValueError(
            f"Wikipedia document {document.title!r} has only "
            f"{len(paragraphs)} usable chunks; need {count}"
        )
    return [f"{document.title}. {paragraph}" for paragraph in paragraphs[:count]]


def _human_query(concept: str, *, target_modality: str) -> str:
    phrase = _human_phrase(concept)
    templates = {
        "image": f"Find an image showing {phrase}.",
        "audio": f"Find a recording of the sound of {phrase}.",
        "video": f"Find a video showing {phrase}.",
        "3d": f"Find a three-dimensional model of {phrase}.",
    }
    return templates[target_modality]


def _human_phrase(concept: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", concept).replace("_", " ").lower()


def _concept_key(concept: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", concept).lower()


def _wikipedia_title(concept: str) -> str:
    return WIKI_TITLE_OVERRIDES.get(
        concept,
        _human_phrase(concept).title(),
    )


def _normalize_title(value: str) -> str:
    return value.replace("_", " ").strip().casefold()


def _opaque_id(prefix: str, *values: str) -> str:
    payload = "\0".join(values).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:32]}"


def _media_type(path: Path) -> str:
    overrides = {
        ".off": "model/vnd.off",
        ".txt": "text/plain",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".png": "image/png",
    }
    return overrides.get(
        path.suffix.lower(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_parquet(path: str | Path):
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            'Install benchmark dependencies with: pip install -e ".[bench]"'
        ) from exc
    return pq.read_table(Path(path))


def _require_concepts(
    rows: Mapping[str, Sequence[Any]],
    concepts: Sequence[str],
    *,
    minimum: int,
    dataset: str,
) -> dict[str, list[Any]]:
    missing = [concept for concept in concepts if len(rows.get(concept, ())) < minimum]
    if missing:
        raise ValueError(f"{dataset} lacks {minimum} samples for: {', '.join(missing)}")
    return {concept: list(rows[concept]) for concept in concepts}


def _counts(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row[key])] += 1
    return dict(sorted(result.items()))


def _query_part_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        for part in row["parts"]:
            result[str(part["modality"])] += 1
    return dict(sorted(result.items()))


def _default_dataset_metadata() -> list[dict[str, Any]]:
    return [
        {
            "id": "cifar100",
            "name": "CIFAR-100 test split",
            "revision": CIFAR_REVISION,
            "license": "unknown; see source dataset card and upstream terms",
            "source_url": (
                "https://huggingface.co/datasets/uoft-cs/cifar100/"
                f"tree/{CIFAR_REVISION}"
            ),
        },
        {
            "id": "esc50",
            "name": "ESC-50",
            "revision": ESC50_REVISION,
            "license": "CC-BY-NC-2.0",
            "source_url": (
                f"https://huggingface.co/datasets/renumics/esc50/tree/{ESC50_REVISION}"
            ),
        },
        {
            "id": "ucf101",
            "name": "UCF101",
            "revision": UCF101_REVISION,
            "license": "research dataset; verify upstream clip terms before reuse",
            "source_url": (
                "https://huggingface.co/datasets/guyuchao/UCF101/"
                f"tree/{UCF101_REVISION}"
            ),
        },
        {
            "id": "modelnet40",
            "name": "Princeton ModelNet40 Auto Aligned mirror",
            "revision": MODELNET40_REVISION,
            "license": (
                "academic research only; original CAD authors retain copyright"
            ),
            "source_url": (
                "https://huggingface.co/datasets/"
                f"{MODELNET40_REPO}/tree/{MODELNET40_REVISION}"
            ),
        },
        {
            "id": "wikipedia",
            "name": "English Wikipedia revision-pinned extracts",
            "revision": "per-page oldid in provenance manifest",
            "license": "CC-BY-SA-4.0 and GFDL",
            "source_url": "https://en.wikipedia.org/",
        },
    ]


def _runtime_dataset_metadata(args: argparse.Namespace) -> list[dict[str, Any]]:
    metadata = _default_dataset_metadata()
    source_paths = {
        "cifar100": [Path(args.cifar_parquet).resolve()],
        "esc50": [Path(path).resolve() for path in args.esc50_parquet],
        "ucf101": [Path(path).resolve() for path in args.ucf101_tar],
    }
    for row in metadata:
        dataset_id = str(row["id"])
        paths = source_paths.get(dataset_id)
        if not paths:
            continue
        missing = [path for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"missing source files for {dataset_id}: "
                + ", ".join(str(path) for path in missing)
            )
        row["source_files"] = [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in paths
        ]
    modelnet_row = next(row for row in metadata if row["id"] == "modelnet40")
    modelnet_files = sorted(Path(args.modelnet_root).resolve().glob("*/*/*.off"))
    modelnet_row["selected_file_count"] = len(modelnet_files)
    modelnet_row["selection_manifest_sha256"] = hashlib.sha256(
        "\n".join(
            f"{path.relative_to(Path(args.modelnet_root).resolve()).as_posix()} "
            f"{_sha256(path)}"
            for path in modelnet_files
        ).encode("utf-8")
    ).hexdigest()
    return metadata


def _create_minio_uploader(args: argparse.Namespace) -> MinioAssetUploader:
    client_kwargs: dict[str, Any] = {}
    endpoint_host = urllib.parse.urlparse(args.s3_endpoint).hostname
    if endpoint_host in {"127.0.0.1", "localhost", "::1"}:
        try:
            from botocore.config import Config
        except ImportError as exc:
            raise RuntimeError(
                'Install S3 dependencies with: pip install -e ".[s3]"'
            ) from exc
        client_kwargs["config"] = Config(proxies={})
    store = S3AssetStore.from_uri(
        args.object_store_uri,
        endpoint_url=args.s3_endpoint,
        region_name=args.s3_region,
        namespace=args.namespace,
        aws_access_key_id=args.s3_access_key,
        aws_secret_access_key=args.s3_secret_key,
        verify=not args.s3_insecure,
        **client_kwargs,
    )
    buckets = {
        str(row.get("Name") or "")
        for row in store.client.list_buckets().get("Buckets", [])
    }
    if store.bucket not in buckets:
        store.client.create_bucket(Bucket=store.bucket)
    return MinioAssetUploader(store)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the strict 1000-asset/200-query public multimodal suite "
            "from pinned real datasets."
        )
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cifar-parquet", required=True)
    parser.add_argument("--esc50-parquet", action="append", required=True)
    parser.add_argument("--ucf101-tar", action="append", required=True)
    parser.add_argument("--modelnet-root", required=True)
    parser.add_argument("--wikipedia-cache", required=True)
    parser.add_argument("--object-store-uri", required=True)
    parser.add_argument("--s3-endpoint", required=True)
    parser.add_argument("--s3-region", default="us-east-1")
    parser.add_argument("--s3-access-key", required=True)
    parser.add_argument("--s3-secret-key", required=True)
    parser.add_argument("--s3-insecure", action="store_true")
    parser.add_argument("--namespace", default="public-multimodal-v1")
    parser.add_argument(
        "--download-modelnet",
        action="store_true",
        help="Download the pinned 220-file ModelNet40 subset before building.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.download_modelnet:
        download_modelnet40_subset(args.modelnet_root)
    image = load_cifar_samples(args.cifar_parquet)
    audio = load_esc50_samples(args.esc50_parquet)
    video = load_ucf101_samples(args.ucf101_tar)
    geometry = load_modelnet40_samples(args.modelnet_root)
    concepts = [
        *image,
        *audio,
        *video,
        *geometry,
    ]
    wikipedia = fetch_wikipedia_documents(
        concepts,
        cache_path=args.wikipedia_cache,
    )
    suite = prepare_public_multimodal_suite(
        output_dir=args.output_dir,
        samples={
            "image": image,
            "audio": audio,
            "video": video,
            "3d": geometry,
        },
        wikipedia_documents=wikipedia,
        uploader=_create_minio_uploader(args),
        dataset_metadata=_runtime_dataset_metadata(args),
    )
    print(suite)


if __name__ == "__main__":
    main()
