"""Keep Studio Source and Preview current while view files change.

This package inspects the files declared by a view provider, watches those
inputs, and shares one rebuild across browsers that need the same source. It
sends view-list, source, build, and presentation events so open workspaces can
refresh without restarting the notebook server.

One coordinator owns each view's monitor and active publication work. Newer
source cancels obsolete work, duplicate requests share a build, and a failed
rebuild leaves the last working preview available when one exists.
"""
