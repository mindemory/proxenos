"""Photos ingester against synthetic Takeout sidecars. No real data lives here."""

import json
import os
from datetime import UTC, datetime

from twin.ingest import photos


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def sidecar(title="IMG_0001.jpg", taken="1709640000", **extra):
    """What Takeout writes next to a photo: 1709640000 is 2024-03-05T12:00:00Z."""
    data = {
        "title": title,
        "description": "",
        "url": f"https://photos.example.com/photo/{title}",
        "photoTakenTime": {"timestamp": taken, "formatted": "Mar 5, 2024"},
        "creationTime": {"timestamp": "1709650000", "formatted": "Mar 5, 2024"},
        "geoData": {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0},
    }
    return {**data, **extra}


def make_photos(root):
    folder = root / "Google Photos"
    put(
        folder / "Trip to Nowhere" / "IMG_0001.jpg.supplemental-metadata.json",
        sidecar(
            description="Sunset",
            geoData={"latitude": 12.34567, "longitude": -76.54321, "altitude": 3.0},
            people=[{"name": "Alex Example"}, {"name": "Sam Sample"}, {"name": ""}],
        ),
    )
    put(folder / "Trip to Nowhere" / "IMG_0002.jpg.json", sidecar("IMG_0002.jpg", "1709726400"))
    # Google has no location, but the photo's own EXIF does.
    put(
        folder / "Photos from 2024" / "DSC_9.jpg.json",
        sidecar(
            "DSC_9.jpg",
            geoDataExif={"latitude": 1.0004, "longitude": 2.0006, "altitude": 0.0},
        ),
    )
    put(
        folder / "Trip to Nowhere" / "metadata.json",
        {
            "title": "Trip to Nowhere",
            "description": "A weekend away",
            "access": "protected",
            "date": {"timestamp": "1709500000", "formatted": "Mar 3, 2024"},
        },
    )
    put(folder / "Plain Album" / "metadata.json", {"title": "Plain Album"})
    put(folder / "shared_album_comments.json", {"sharedAlbumComments": []})
    put(folder / "user-generated-memory-titles.json", {"title": "x"})
    return folder


def by_id(records):
    return {r["id"]: r for r in records if r is not None}


def test_sidecars_become_photo_records(tmp_path):
    records = by_id(photos.read_meta(make_photos(tmp_path)))

    trip = records["Trip to Nowhere/IMG_0001.jpg"]
    assert trip == {
        "id": "Trip to Nowhere/IMG_0001.jpg",
        "ts": "2024-03-05T12:00:00Z",
        "kind": "photo",
        "title": "IMG_0001.jpg",
        "geo": {"lat": 12.346, "lon": -76.543},
        "people": ["Alex Example", "Sam Sample"],
        "album": "Trip to Nowhere",
        "description": "Sunset",
        "url": "https://photos.example.com/photo/IMG_0001.jpg",
    }
    nowhere = records["Trip to Nowhere/IMG_0002.jpg"]
    assert nowhere["geo"] is None  # 0, 0 means no location
    assert nowhere["people"] == []
    assert nowhere["description"] is None
    assert nowhere["ts"] == "2024-03-06T12:00:00Z"
    assert records["Photos from 2024/DSC_9.jpg"]["geo"] == {"lat": 1.0, "lon": 2.001}


def test_album_metadata_with_a_date_or_description_is_a_record(tmp_path):
    records = by_id(photos.read_meta(make_photos(tmp_path)))
    album = records["Trip to Nowhere/metadata.json"]
    assert album == {
        "id": "Trip to Nowhere/metadata.json",
        "ts": "2024-03-03T21:06:40Z",
        "kind": "album",
        "title": "Trip to Nowhere",
        "description": "A weekend away",
        "album": "Trip to Nowhere",
    }
    # An album with only a title says nothing its folder name doesn't, and other JSON isn't photos.
    assert sorted(records) == [
        "Photos from 2024/DSC_9.jpg",
        "Trip to Nowhere/IMG_0001.jpg",
        "Trip to Nowhere/IMG_0002.jpg",
        "Trip to Nowhere/metadata.json",
    ]


def test_an_album_without_a_date_takes_the_files_modified_time(tmp_path):
    folder = tmp_path / "Google Photos"
    path = put(folder / "Old Album" / "metadata.json", {"title": "Old Album", "description": "d"})
    mtime = datetime(2023, 7, 1, 9, 30, tzinfo=UTC).timestamp()
    os.utime(path, (mtime, mtime))
    (record,) = photos.read_meta(folder)
    assert record["ts"] == "2023-07-01T09:30:00Z"


def test_a_sidecar_without_a_title_is_named_for_its_media_file(tmp_path):
    folder = tmp_path / "Google Photos"
    data = sidecar()
    del data["title"]
    put(folder / "Album" / "IMG_77.jpg.supplemental-metadata.json", data)
    (record,) = photos.read_meta(folder)
    assert record["id"] == "Album/IMG_77.jpg"


def test_same_name_different_time_in_one_album_are_two_photos(tmp_path):
    folder = tmp_path / "Google Photos"
    put(folder / "Photos from 2020" / "IMG_1.jpg.json", sidecar("IMG_1.jpg", "1600000000"))
    put(folder / "Photos from 2020" / "IMG_1.jpg(1).json", sidecar("IMG_1.jpg", "1500000000"))
    put(folder / "Photos from 2021" / "IMG_1.jpg.json", sidecar("IMG_1.jpg", "1600000000"))
    records = photos.read_meta(folder)
    assert sorted(r["id"] for r in records) == [
        "Photos from 2020/IMG_1.jpg",
        "Photos from 2020/IMG_1.jpg#2",
        "Photos from 2021/IMG_1.jpg",
    ]
    # The earlier photo keeps the plain id, whichever file is read first.
    assert by_id(records)["Photos from 2020/IMG_1.jpg"]["ts"] == "2017-07-14T02:40:00Z"


def test_bad_files_are_skipped_not_fatal(tmp_path):
    folder = make_photos(tmp_path)
    put(folder / "Trip to Nowhere" / "broken.jpg.json", "{not json")
    put(folder / "Trip to Nowhere" / "no-time.jpg.json", {"title": "x", "photoTakenTime": {}})
    put(
        folder / "Trip to Nowhere" / "bad-time.jpg.json",
        sidecar("bad.jpg", taken="never"),
    )
    put(folder / "Trip to Nowhere" / "huge-time.jpg.json", sidecar("huge.jpg", taken="9" * 30))
    put(folder / "Trip to Nowhere" / "list.json", [1, 2, 3])
    records = photos.read_meta(folder)
    assert records.count(None) == 4
    assert len([r for r in records if r]) == 4


def test_ingest_writes_the_meta_stream_and_reruns_are_no_ops(tmp_path):
    folder = make_photos(tmp_path)
    put(folder / "Trip to Nowhere" / "broken.jpg.json", "{not json")
    vault = tmp_path / "vault"

    first = photos.ingest(vault, folder)
    assert first == {"read": 4, "added": 4, "updated": 0, "months_written": 1, "skipped": 1}
    raw = vault / "raw" / "photos" / "meta"
    assert sorted(p.name for p in raw.iterdir()) == ["2024-03.jsonl"]
    records = [json.loads(line) for line in (raw / "2024-03.jsonl").read_text().splitlines()]
    assert len(records) == 4
    assert all(r["ts"].endswith("Z") for r in records)

    again = photos.ingest(vault, folder)
    assert again["added"] == 0 and again["updated"] == 0 and again["months_written"] == 0


def test_a_missing_folder_is_an_error(tmp_path):
    try:
        photos.ingest(tmp_path / "vault", tmp_path / "nowhere")
    except FileNotFoundError as e:
        assert "nowhere" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")
