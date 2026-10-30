pragma Singleton
import QtQuick

// How the bar widget finds the panel that owns the taskbar's state.
QtObject {
  property var taskbar: null
  // Combine modules on screen. Without one, the taskbar keeps its own bar.
  property int modules: 0
}
