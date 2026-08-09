import { useNavigate } from 'react-router-dom';
import { TaskForm } from './TaskForm';

export function CreateTaskPage(): JSX.Element {
  const navigate = useNavigate();
  return (
    <div>
      <h2>New task</h2>
      <TaskForm mode="create" onSaved={() => navigate('/')} onCancel={() => navigate('/')} />
    </div>
  );
}
