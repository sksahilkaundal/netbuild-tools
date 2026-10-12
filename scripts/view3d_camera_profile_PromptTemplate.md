# Prompt template: save / restore 3D views (camera, zoom, template)

Script: `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py`
Profiles: `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profiles\`
Skill: `view3d-camera-profile`

## What it does

The script saves a set of 3D views to a JSON profile and can put them back exactly.
The views are every view whose name starts with `NAME_PREFIX`, for example all "Enscape View ..." views.

For each view it saves:
- the camera: eye position, up direction and forward direction;
- the crop box and section box, including their transforms;
- the locked or unlocked orientation;
- every instance parameter;
- the **window zoom**, for the views that are open on screen when you capture.

It also saves the **view template** each view uses:
- every parameter, and which ones are ticked under "Include";
- V/G for each category (visible, plus overrides);
- filters, worksets and RVT link overrides;
- graphic display options: style, silhouettes, sketchy lines, background, shadow and sunlight intensity.

There are two modes, set in the CONFIG block:
- `MODE = "capture"` writes the profile and changes nothing in the model. Add `OVERWRITE_PROFILE = True` to replace a profile. The old one is kept as `.bak_<time>.json`, and views that are closed now keep the zoom stored in the old profile.
- `MODE = "restore"` puts the views back. Run it with `DRY_RUN = True` first: it lists every difference and changes nothing. `DRY_RUN = False` writes one transaction per view or template, then re-checks the result in the same call.
  - `RESTORE_TEMPLATES = True` also restores the template.
  - `CREATE_MISSING_VIEWS = True` (the default) recreates deleted views by name.
  - A deleted template is recreated from one of its views.

## Prompt: save views (capture)

> Connect to Revit PID `<PID>` and confirm the active document is `<MODEL TITLE>`.
>
> Using `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py` in **capture**
> mode, save every 3D view whose name starts with "`<NAME PREFIX>`" to
> `scripts\view3d_camera_profiles\<PROFILE NAME>.json`. Save the camera, crop and section
> box, lock state, all view properties, the window zoom of the views open on my
> screen, and the view template(s) they use. Read-only: change nothing in the model.
> Tell me which views had no zoom saved because they were not open.

Before you capture, open and tile the views on screen (View > Tile) so their zoom is saved.

## Prompt: restore views (dry run, then apply)

> Connect to Revit PID `<PID>` and confirm the active document is `<MODEL TITLE>`.
>
> Using `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py` in **restore**
> mode with the profile `scripts\view3d_camera_profiles\<PROFILE NAME>.json`, dry run:
> list per view what differs from the profile (camera, crop, section box, lock,
> parameters, zoom) and any view that is missing. <Also check the view template
> `<TEMPLATE NAME>` (RESTORE_TEMPLATES = True).> <Only these views: `<NAMES>`.>
> Then stop and wait for "apply".

After you check the list, reply **"apply"**. That runs the same settings with `DRY_RUN = False`. Then synchronise with central yourself.

### Ready-made: the SW0O Enscape views (saved 2026-10-06)

> Connect to Revit PID `<PID>` and confirm the document is
> `ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001`. Using
> `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py` in restore mode with
> `scripts\view3d_camera_profiles\SW0O_BM-950001_Enscape_Views.json`, dry run all
> 17 "Enscape View" views, their zoom, and the template `05 _ Enscape Export View`
> (RESTORE_TEMPLATES = True). Show the differences and wait for "apply".

## Prompt: after a Revit restart (same zoom on all the views again)

> Connect to Revit PID `<PID>` and confirm the document is `<MODEL TITLE>`. **Before Enscape is
> started**, open all the views in the profile
> `scripts\view3d_camera_profiles\<PROFILE NAME>.json` that have a saved zoom. Tile them
> (PostableCommand.TileWindows) and then, using
> `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py` in restore mode, dry run the
> zoom (and camera) against the profile. Wait for "apply".

Order matters:
1. **Open** the views. Do this with Enscape stopped, otherwise it re-processes every view as it becomes active.
2. **Tile** them. The profile was saved with 16 views tiled 4x4, each window about 518x257 px (`window_px`). Same-size tiles give the same zoom whatever their order.
3. **Zoom** with `ZoomAndCenterRectangle`.

If you zoom before tiling, each view is fitted to a full-size window, and the result changes once the windows are tiled.

## Prompt: Enscape window-capture export (after restoring the zoom)

> Revit is open with all the models and the relevant worksets. Restore the zoom of the
> "Enscape View" views from `scripts\view3d_camera_profiles\SW0O_BM-950001_Enscape_Views.json`
> using `C:\SK\OneDrive\Netbuild\scripts\view3d_camera_profile.py`: open them, tile them,
> then zoom, all with Enscape stopped. Then start Enscape on screen 2 (move it there if it
> opens on screen 1). For each view, switch to it, wait for Enscape to sync, and click
> Screenshot. Save it as `<Revit view name>.png` in `C:\SK\Projects\ProjectA\Render\<yymmdd>`.
> Allow 120 s per export at most; if one takes longer, notify me and never force-kill Enscape.

Revit is on screen 1 and Enscape on screen 2. Enscape's Screenshot button is at about (198, 24) on screen 2's top toolbar. Batch Rendering is not used, because it ignores the view's crop and zoom.

## Notes and gotchas

- **Zoom only works on views open on screen.** Revit only exposes the zoom of an open view window.
  - Capture saves the zoom of the views that are open.
  - Restore zooms only the views that are open. It opens closed views only with `OPEN_VIEWS_FOR_ZOOM = True`.
  - The zoom is fitted to the current window, so tile the windows the same way as at capture. The profile records each window's size in pixels as `window_px`.
- **Enscape makes Revit busy.** When the active view changes, or its camera changes, Enscape re-processes the view ("printing" in the journal), which took about 4 minutes on SW0O. MCP calls time out meanwhile but stay queued and run afterwards: don't re-send them, just wait. For big restores, pause the Enscape live window first.
- **Not restorable from JSON.** The API does not expose these, so they can't be saved:
  - the custom model-category ticks inside a "Custom" RVT Links override (restore warns when one of these differs);
  - Lighting details, Photographic Exposure and Rendering Settings of the template.

  To keep those exactly, also duplicate the template in the model as a backup.
- Views and templates are matched by **name**, never by id. If a view is renamed, restore treats it as missing and recreates it.
- In a workshared model, restore skips an element owned by another user, or one updated in central (reload latest first). Never save or sync from the script; sync yourself afterwards.
- Revit 2026: `ElementId` has no `.IntegerValue`. The script uses `.Value`.

## History

- 2026-10-06: first capture of the 17 "Enscape View" views in `ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001` (Revit 2026, pid 39244), with template `05 _ Enscape Export View`. 16 views were open and tiled 4x4, so their zoom was saved; the plain "Enscape View" was closed, so it has no zoom.
  - The restore dry run found 0 differences (views, template and zoom), so capture and compare are verified.
  - The **apply path is not fully verified**. A rolled-back test on temporary views did commit its restore-view and restore-template transactions without error, according to the journal. Its re-check output was lost to a timeout, because creating 3D views took minutes each in this model. On the first real apply, do one view first (`ONLY_VIEWS`) and check the `commit=` and `re-check:` lines.
