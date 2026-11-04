"""
dataset_zip.py - hand a dataset to someone else as ONE zip file, and merge such a zip into a project.  No Qt here, so it is testable.

What is in the zip: every ANNOTATED image (including confirmed ones with no objects) with its boxes (by class NAME), the per-box distance
picks and the LiDAR depth picture of the frame, plus index.json (who made it, the class names, one entry per image).  Videos, unannotated
frames, generated distortions (they are recreated), models and every setting stay out.

    index.json   images/<uid>.jpg   depth/<uid>.png

Importing merges: the same picture (same id, or the same file bytes) is never added twice; a picture that is annotated differently on both
sides is a conflict (keep mine / take theirs / newest edit wins); class names the project does not have are added at the END of its list, so
the numbers on the labels you already have never change.  The merge itself is share_zip's (analyze_entries / apply_import).
"""
import json
import os
import time
import zipfile

import annotator_core as ac
import share_zip as sz


def export_zip(project, zip_path, me, progress_cb=None):
    """Writes every annotated image of `project` into `zip_path`.  Returns {'count', 'with_depth', 'path'}."""
    ids = sz.shareable_ids(project)
    people = dict(project.manifest.get("people", {}))
    people[me["id"]] = me["name"]
    entries = []
    tmp = zip_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:               # pictures are compressed already
        for n, img_id in enumerate(ids, 1):
            e = sz._entry(project, img_id, me)
            z.write(project.image_path(img_id), f"images/{e['uid']}.jpg")
            if e["has_depth"]:
                z.write(project.depth_path(img_id), f"depth/{e['uid']}.png")
            entries.append(e)
            if progress_cb:
                progress_cb(n, len(ids))
        body = {"format": sz.FORMAT, "owner": {"id": me["id"], "name": me["name"]}, "updated_at": time.time(), "people": people,
                "classes": list(project.classes),
                "images": sorted(entries, key=lambda x: (x.get("set") or "", x.get("sample_index") or 0, x["uid"]))}
        z.writestr(sz.INDEX, json.dumps(body))
    os.replace(tmp, zip_path)
    project.manifest["people"] = people
    project.save_manifest()
    return {"count": len(entries), "with_depth": sum(1 for e in entries if e["has_depth"]), "path": zip_path}


def read_zip(zip_path, workdir):
    """Unpacks the zip into `workdir` (a new folder) and returns the folder list the merge functions take."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if sz.INDEX not in names:
            raise ValueError("This zip is not a dataset zip from the annotator (it has no index.json).")
        root = os.path.realpath(workdir)
        for n in names:
            if os.path.isabs(n) or ".." in n.replace("\\", "/").split("/") or not os.path.realpath(os.path.join(workdir, n)).startswith(root):
                raise ValueError(f"The zip holds a file with an unsafe name: {n}")
        z.extractall(workdir)
    idx = sz._read_index(workdir)
    if idx is None:
        raise ValueError("The zip's index.json cannot be read, or it is from a different program version.")
    return [{"path": workdir, "index": idx}]


def plan_zip(project, zip_path, workdir, me, progress_cb=None):
    """Looks at what importing the zip would do; nothing is changed.  Returns the share_zip plan (new / update / conflicts / duplicates ...)."""
    folders = read_zip(zip_path, workdir)
    merged = sz.merge_folders(folders)
    plan = sz.analyze_entries(project, merged["entries"], merged["people"], me, progress_cb)
    plan["pending"] = merged["pending"]
    # every class of the zip comes along (in the zip's order), also the ones no image uses yet; names are matched, new ones go at the END
    wanted = [c for c in folders[0]["index"].get("classes", []) if isinstance(c, str)]
    new = [c for c in wanted if c not in project.classes and not ac.Project.validate_class_name(c, project.classes)]
    new += [c for c in plan["new_classes"] if c not in new]
    plan["new_classes"] = new
    plan["bad_classes"] = [c for c in plan["bad_classes"] if c not in new]
    return plan


def apply_zip(project, plan, choices, me, progress_cb=None):
    """choices = {uid: 'mine' | 'theirs'} for the conflicts; None = whoever edited last wins."""
    return sz.apply_import(project, plan, choices, me, progress_cb)
