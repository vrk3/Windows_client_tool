# Runtime hook: set PYQTGRAPH_QT_LIB before pyqtgraph is imported.
# This forces pyqtgraph to use PyQt6 without auto-detection,
# which avoids __import__('PyQt6.QtCore') failing in the frozen exe.
import os
os.environ['PYQTGRAPH_QT_LIB'] = 'PyQt6'
