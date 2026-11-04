# Towers (playground game)

Capture every tower on the map. White towers are yours.

* Drag from your tower to another tower to open a **path**; drag to the same tower again (or click the path) to close it.
* A tower makes troops only through its open paths; the output is shared between them. Stored troops set the level: 20 = level 2, 40 = level 3, 60 = level 4
  (output x1.5 per level, and a level-N tower can have N paths). It can store up to 80; the 20 above level 4 is a buffer so the level does not drop at once when attacked.
* Only troops arriving from your own towers add to a tower's count. Sending troops never lowers the level; enemy troops arriving do.
* Opposite paths between towers of different owners fight head-on: troops cancel one for one, so the stronger stream gets through.
* Settings: enemies (1-3), towers (6-40), start level for everybody, AI aggression, seed (0 = random), speed. Space pauses.
