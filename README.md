# MYN-FaceRig
A Blender add-on that builds an on-screen rig of sliders and 2D pads which drive a mesh's shape keys through drivers.

## What it does

- Creates a lightweight armature ("face rig") that acts as a control panel — no deforming bones, just draggable knobs.
- Each control is a bone with a custom circular shape, constrained to move along a track (slider) or within a square (2D pad).
- Automatically generates text labels, group headers, a panel title, and background tracks, and lays them out in columns that grow/shrink as you add or remove controls.
- Controls can be organized into named **groups**, and groups placed into numbered **columns**, for a tidy multi-section panel.

## Tested Environment

- Blender 5.2+

## Installation

1. Download the zip file from `Release` page.
2. In Blender: `Edit > Preferences > Add-ons > Install...`, select the zip file, and enable "MYN-FaceRig".
3. Open the 3D Viewport sidebar (`N`) and find the **FaceRig** tab.

## Basic Workflow

1. **Create or detect a rig**
   - Click **New Face Rig** to create a fresh control-panel armature (upright by default, scaled down to a comfortable on-screen size), or
   - Click **Detect / Read Face Rig** to find an existing CT FaceRig already in the file (useful after appending/linking one from another file).

2. **Set the target mesh**
   - Pick the mesh with shape keys you want to control, then click **Set Target Mesh**. This mesh is remembered on the rig itself.

3. **Add a group**
   - Give it a name and a column number, then click **Add Group**. Controls must belong to a group, and groups can be arranged side-by-side by column.

4. **Add controls**
   - **Slider**: choose one-sided (0→1, one shape key) or two-sided (−1→1, two shape keys), horizontal or vertical orientation, pick the shape key(s), optionally set a custom name/label, then **Add Slider Control**.
   - **2D Pad**: pick up to four shape keys (up/down/left/right), then **Add 2D Pad Control**. Diagonal drags blend two shape keys at once.

5. **Manage controls**
   - The Controls list shows every control with its group; click the **X** to delete one (this also removes its bone, drivers, and track).
   - Deleting a group deletes every control inside it.

6. **Rebuild Layout**
   - Recomputes label positions, track placement, and the panel's overall size. This runs automatically after adding/removing groups or controls, but you can trigger it manually any time (e.g. after editing labels).

## Limitations

- One target mesh per rig at a time (though a file can contain multiple rigs, each with its own target).
- Layout is column-based and top-down; there's no free-form dragging of groups within the panel yet.
- Deleting a control removes its driver(s) only where the driver's variable target matches that exact bone — manually-added drivers won't be touched.

## Why this Add-on exist

   - At around August 2026, I'm tired of spending hours to setup a face-rig for MMDs, I want to speed up the progress, so I turn the whole long process into an add-on that only require clicking few buttons. 
   - Huge Credit: I get the idea from [Muhammad Farhani](https://www.youtube.com/@farhanimuhammad), It made a video that teach you how to make a facerig with existed shape-keys, without the video, the add-on would not exist.

If you have any problems or ideas for the add-on, feel free to make issues or contact me!
