"""Read and change workspace and artifact files through contained trees.

``files.FileTree`` owns every file change under one root. ``read`` returns
content with an opaque ``Version``. ``write`` accepts an expected ``Version``
or ``ABSENT``, ``remove`` accepts an expected ``Version`` or ``TreeVersion``,
``publish`` moves a staged entry onto a name that must stay absent, and
``lock`` holds a cross-process lock file. Each verb refuses a path that leaves
its root or crosses a symlink or Windows junction, and uses the strongest
primitive the filesystem offers. Callers state preconditions with versions and
never handle temporary names, syncs, or displaced copies.

Provider builds are the only lower-privilege writers. ``FileTree.ingest``
copies their output through directory handles into a directory that only
Studio writes, so publication and serving never read a tree that a build can
change.
"""
