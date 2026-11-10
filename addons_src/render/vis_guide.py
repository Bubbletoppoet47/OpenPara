"""vis_guide.py - the guide of the Visualize tab (the Guide button, F1): what each stage is for and how to get from a model to a picture."""

GUIDE = """
<h2>Visualize</h2>
<p>Lit pictures and videos of a part or an assembly. Visualize works on <b>its own copy</b> of the model, so nothing you do here changes
the original.</p>

<h3>1. Bring in a model</h3>
<ul>
<li><b>From a part or an assembly that is on screen:</b> its <b>Visualize</b> ribbon tab &gt; <b>Preview / Render</b>, or <b>Add &gt; Visualize</b>.
It does not have to be saved first.</li>
<li><b>From an empty Visualize tab</b> (File &gt; New Visualize): <b>Import part or assembly...</b> lists what is open and lets you browse for
a .gpd or .gpa file. You can also drop a file on the page.</li>
<li><b>Import source...</b> in the bar shows another model in the same tab. The sun, the picture and video settings and the output folder
stay; the cameras, looks, floor and spot light start again, because they depend on the model.</li>
<li><b>Update from original</b> reads the same model again after you changed it. Looks, lights and cameras stay.</li>
</ul>

<h3>2. The three stages</h3>
<table cellspacing="0" cellpadding="4">
<tr><td><b>Previs</b></td><td>The simple, fast view. Set up looks, lights and cameras here. It shows the cameras (the selected one in orange),
the sun arrow (yellow) and the spot light.</td></tr>
<tr><td><b>Preview</b></td><td>A live lit view of the same scene: sky light, sun, shadows. Orbit freely or look through a camera.</td></tr>
<tr><td><b>Render</b></td><td>The finished picture or video, ray traced. This is the slow, accurate one, written to a file.</td></tr>
</table>
<p>In the 3D view the left button turns, the wheel zooms and the middle button pans.</p>

<h3>3. Looks, lights and floor</h3>
<ul>
<li><b>Appearance:</b> one block for each body. Colour; Roughness (0 mirror-like, 1 matt); Metallic (0 paint or plastic, 1 bare metal). The
start values come from the part's material; <b>Material default</b> goes back to them.</li>
<li><b>Sun and sky:</b> date, clock time, UTC offset, latitude and longitude give the real position of the sun; the readout shows its height
and direction. <b>North direction</b> says where north is in the model. <b>Sun shadows</b> off leaves only soft sky light. <b>Even light</b>
adds a plain white light from everywhere, useful at night or with the sun off.</li>
<li><b>Spot light:</b> where it is, the point it aims at, power, cone angle and colour.</li>
<li><b>Floor:</b> a flat plane under the model. <b>At the bottom of the model</b> puts it there. With the floor off the model floats in the sky.</li>
<li><b>Scene &gt; Up direction of the model</b> stands the model on another side. A part drawn on the Front plane may need +Y.</li>
</ul>

<h3>4. Cameras</h3>
<ul>
<li>Move around until you like the view, then <b>Add from current view</b>. <b>Add view</b> makes a standard camera (Iso, Front, Top ...)
that frames the whole model.</li>
<li>Select a camera, then <b>Look through</b> it, <b>Set from current view</b> to move it, or type its position, target and field of view.</li>
<li>Double-click a name to rename it. The name becomes the file name of its picture.</li>
</ul>

<h3>5. A video</h3>
<ul>
<li>Tick two or more cameras. They are the keyframes, in the order of the list (<b>Move up</b> / <b>Move down</b>).</li>
<li><b>Video path:</b> curved or straight, constant speed or a gentle start and stop, the length in seconds and the frames per second.</li>
<li>The bar under the 3D view scrubs along the path, in Previs and in Preview.</li>
</ul>

<h3>6. Render</h3>
<ul>
<li><b>What to render:</b> the selected camera, all cameras, the video, or a fast preview of a still or of the video (small and grainy,
nothing is saved to your folder).</li>
<li><b>Picture size</b> and <b>Quality</b> (samples per pixel) set the time: it grows in proportion to pixels x samples. For a test use
Draft at 800 x 600; for a final picture High at 1920 x 1080 or more.</li>
<li><b>Exposure</b> in stops: + brighter, - darker. <b>Background:</b> the sky, a solid colour, or transparent (a PNG with alpha).</li>
<li><b>Remove single bright pixels</b> cleans the white speckles shiny metal can make. <b>Denoise</b> needs an NVIDIA graphics card.</li>
<li>Pictures and videos go to the project's own <b>output</b> folder unless you choose another one.</li>
</ul>
<table cellspacing="0" cellpadding="4">
<tr><td><b>F5</b></td><td>Still preview of the selected camera</td></tr>
<tr><td><b>F11</b></td><td>Render the selected camera</td></tr>
<tr><td><b>F12</b></td><td>Render all cameras</td></tr>
<tr><td><b>Ctrl+F12</b></td><td>Render the video</td></tr>
<tr><td><b>Esc</b></td><td>Stop</td></tr>
</table>

<h3>7. The project</h3>
<p>A Visualize project is a folder whose name ends in <b>.gpv</b>. It holds the settings, its own copy of the model (with every part of an
assembly) and the output folder, so it can be moved or sent to someone as it is. It is saved with <b>File &gt; Save</b>, or by itself at the
first render: beside the part or assembly, named after it. Open it again with <b>File &gt; Open Project Folder...</b></p>
<p><b>Project</b> in the bar also exports and imports the general settings (sun, spot light, floor, picture, quality, video) and the
cameras, to use them in another project.</p>

<h3>Speed and limits</h3>
<ul>
<li>The renderer is Mitsuba 3, a path tracer: light bounces as it does for a real camera. It runs as its own process, so a problem there
cannot close the program, and Stop ends it at once.</li>
<li>The first line of the log says how it runs: <b>cuda</b> is the graphics card, <b>llvm</b> the fast processor mode, <b>scalar</b> the slow one.</li>
<li>Looks are colour, roughness and metallic only: no glass, textures or bumps.</li>
<li>Curved faces are drawn from the same mesh as the 3D view, so a very close camera may show facets.</li>
</ul>
"""
