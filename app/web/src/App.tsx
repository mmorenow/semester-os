import { Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/app-shell'
import { ConnectPage } from '@/features/connect/connect-page'
import { SchoolAssignmentsPage } from '@/features/school/assignments-page'
import { CourseDetailPage } from '@/features/school/course-detail-page'
import { SetupPage } from '@/features/onboarding/setup-page'
import { GcalConnectReturn } from '@/features/school/gcal-connection'
import { SchoolNotesPage } from '@/features/school/notes-page'
import { SchoolCoursesPage } from '@/features/school/school-courses-page'
import { SchoolLayout } from '@/features/school/school-layout'
import { SchoolTodayPage } from '@/features/school/school-today-page'
import { SchoolWeekPage } from '@/features/school/school-week-page'

export default function App() {
  return (
    <>
      {/* OAuth returns to `/?gcal=...` on any route, popup or tab, so the handoff sits above the routes. */}
      <GcalConnectReturn />
      <Routes>
        <Route element={<AppShell />}>
          <Route element={<SchoolLayout />}>
            <Route index element={<SchoolTodayPage />} />
            <Route path="week" element={<SchoolWeekPage />} />
            <Route path="assignments" element={<SchoolAssignmentsPage />} />
            <Route path="courses" element={<SchoolCoursesPage />} />
            <Route path="courses/:id" element={<CourseDetailPage />} />
            <Route path="notes" element={<SchoolNotesPage />} />
            <Route path="connect" element={<ConnectPage />} />
            <Route path="setup" element={<SetupPage />} />
            <Route path="*" element={<SchoolTodayPage />} />
          </Route>
        </Route>
      </Routes>
    </>
  )
}
