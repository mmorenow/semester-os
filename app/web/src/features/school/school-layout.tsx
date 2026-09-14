import { Outlet } from 'react-router-dom'
import { SchoolGcalAlert } from './gcal-connection'
import { useSchoolShortcuts } from './use-school-shortcuts'

/** Wraps every page: mounts the nav hotkeys (T, W, A, C, N) and the Google connection callout. */
export function SchoolLayout() {
  useSchoolShortcuts()
  return (
    <div className="flex flex-col gap-4">
      <SchoolGcalAlert />
      <Outlet />
    </div>
  )
}
