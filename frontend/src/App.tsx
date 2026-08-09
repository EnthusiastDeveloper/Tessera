import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { RouteGuard } from './routes/RouteGuard';
import { LoginScreen } from './views/auth/LoginScreen';
import { SetupScreen } from './views/auth/SetupScreen';
import { AppShell } from './views/shell/AppShell';
import { ComingSoon } from './views/shell/ComingSoon';
import { CreateTaskPage } from './views/tasks/CreateTaskPage';
import { EditTaskPage } from './views/tasks/EditTaskPage';

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
            <Route index element={<ComingSoon title="Timeline" note="Built in Stage 9d." />} />
            <Route path="tasks/new" element={<CreateTaskPage />} />
            <Route path="tasks/:instanceId/edit" element={<EditTaskPage />} />
            <Route
              path="backlog"
              element={<ComingSoon title="Backlog" note="Built in Stage 9c." />}
            />
            <Route
              path="notifications"
              element={<ComingSoon title="Notifications" note="Built in Stage 9e." />}
            />
            <Route
              path="settings"
              element={<ComingSoon title="Settings" note="Built in Stage 9f." />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
