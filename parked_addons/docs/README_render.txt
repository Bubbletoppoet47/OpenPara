RENDER STUDIO - photorealistic pictures of a part or an assembly
=================================================================
Start it with run_render_studio.bat (the first time it installs the packages: mitsuba, pyvista, pyvistaqt, PyQt6, build123d).
It is a separate program for now; it only READS your .gpd / .gpa files and never changes them.

The renderer is Mitsuba 3, a physically based path tracer (light bounces like in a real camera: soft shadows, reflections, sky light).
It runs as its own process, so if it ever fails your window stays open; "Stop" ends it at once.

1. OPEN A MODEL
   File > Open model...  a part (.gpd) or an assembly (.gpa).  An assembly shows the parts that are visible in it, in their places.
   The 3D view shows the model with its colours, the floor, the sun arrow (yellow), the spot light (orange) and every camera (blue pyramids; the
   selected camera is orange).  Left button rotates, wheel zooms, middle button pans.

2. APPEARANCE  (panel "Appearance")
   One block per body, with only three settings:
     Colour    click the swatch.
     Roughness 0 = mirror-like, 1 = completely matt.
     Metallic  0 = paint / plastic, 1 = bare metal (metal takes its colour from the reflections; it looks dark in a dark sky).
   The start values come from the part's material (steel, aluminium, brass, ABS ... see render_scene.py, LOOKS).  "Material default" goes back.
   Later, when this is built into the modeller, the colour will be set in the part and the roughness / metallic in the material; here it is all per body.

3. SUN AND SKY  (panel "Sun and sky")
   Date, clock time, UTC offset (Arizona = -7), latitude and longitude give the real position of the sun; the readout shows its height and compass
   direction.  "North direction" says where north is in your model (0 = the model's +Y is north and +X is east).
   Brightness and Haze (2 = clear air, 6+ = hazy) change the light.  "Even light" adds a plain white light from everywhere (use it with the sun off).
   "Sun shadows" ON: hard sun and sky.  OFF: only soft sky light, so there are no cast shadows (a little darker contact shadows remain).
   Night (sun below the horizon): the sky is almost black - use the spot light or "Even light".

4. SPOT LIGHT  (panel "Spot light")  Position, the point it aims at (mm, model coordinates), power, cone angle and colour.

5. FLOOR  (panel "Floor")
   A flat plane, perpendicular to the model's UP direction.  Height is measured along that direction (mm); "At the bottom of the model" puts it
   under the model.  Which side of the model is UP is set in "Scene > Up direction of the model" (+Z, -Z, +Y, -Y, +X, -X): this turns the whole
   picture (sun, sky, floor, cameras) so the model stands on that side.  After changing it, cameras can be re-aimed automatically.
   With the floor off the model floats in the sky (below the horizon the sky is black).

6. CAMERAS  (panel "Cameras")
   Move around in the 3D view until you like what you see, then "Add from current view".  "Add view" makes a standard camera (Iso, Front, Back,
   Right, Left, Top) that frames the whole model.  Select a camera and: "Look through" shows the 3D view from it; "Set from current view" moves it
   there; or type its position, target and field of view.  Double-click a name to rename it (the name becomes the file name).
   The picture size and shape come from Output (the camera pyramid shows the frame).

7. OUTPUT
   Picture size (or custom), Quality = samples per pixel (more = smoother and slower; Draft 32, Normal 128, High 512; the time grows in proportion
   to samples x pixels), Exposure in stops (+ brighter), Background: Sky, a solid colour, or Transparent (PNG with alpha - the floor, if on, stays).
   "Remove single bright pixels" cleans white speckles (fireflies) that shiny metal can make.
   Folder: where the PNG files go (asked at the first render).  "File name start" goes in front of the camera name.

8. RENDER
   "Preview (fast)" - the selected camera at 480 px wide, 24 samples, shown below (nothing is saved to your folder).
   "Render selected camera" - full quality, one file.   "Render ALL cameras" - one PNG per camera in the folder, shown in the list
   (double-click a name to open the picture).   F5 / F11 / F12 are the shortcuts, Esc stops.

9. SAVE
   File > Save render project saves a .gpr file: which model, every look, the lights, the floor, the cameras and the output settings.  Open it again
   later with File > Open render project...  (the model file must still be there).

SPEED AND LIMITS
 * Mitsuba uses the processor; if the NVIDIA graphics card libraries (CUDA) or LLVM are found it uses them, otherwise a slower mode. The log
   line "Renderer: Mitsuba ... (variant)" says which one: cuda = graphics card, llvm = fast processor mode, scalar = slow processor mode.
 * Quick settings for tests: Draft quality, 800 x 600.  Final pictures: High, 1920 x 1080 or more.
 * Glass / transparent materials, textures and bumps are not in this version (colour, roughness and metallic only, by design).
 * Curved faces are drawn from the same mesh as the 3D view of the modeller (fine for pictures; a very close camera may show facets).
