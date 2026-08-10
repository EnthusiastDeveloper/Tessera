import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { RouteGuard } from './routes/RouteGuard';
import { LoginScreen } from './views/auth/LoginScreen';
import { SetupScreen } from './views/auth/SetupScreen';
import { AppShell } from './views/shell/AppShell';
import { ComingSoon } from './views/shell/ComingSoon';
import { CreateTaskPage } from './views/tasks/CreateTaskPage';
import { EditTaskPage } from './views/tasks/EditTaskPage';
import { TaskDetailPage } from './views/tasks/TaskDetailPage';
import { NotificationsPanel } from './views/notifications/NotificationsPanel';
import { SettingsPage } from './views/settings/SettingsPage';
import { TimelinePage } from './views/timeline/TimelinePage';

function App(): JSX.Element {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <Routes>
          <Route
            path="/setup"
            element={
              <RouteGuard allow={['setup_required']}>
                <SetupScreen />
              </RouteGuard>
            }
          />
          <Route
            path="/login"
            element={
              <RouteGuard allow={['unauthenticated']}>
                <LoginScreen />
              </RouteGuard>
            }
          />
          <Route
            path="/"
            element={
              <RouteGuard allow={['authenticated']}>
                <AppShell />
              </RouteGuard>
            }
          >
            <Route index element={<TimelinePage />} />
            <Route path="tasks/new" element={<CreateTaskPage />} />
            <Route path="tasks/:instanceId/edit" element={<EditTaskPage />} />
            <Route path="tasks/:instanceId" element={<TaskDetailPage />} />
            <Route
              path="backlog"
              element={<ComingSoon title="Backlog" note="Not yet scheduled - see implementation-plan.md." />}
            />
            <Route path="notifications" element={<NotificationsPanel />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
