import { stopBackend } from './backend-process';

export default function globalTeardown(): void {
  stopBackend();
}
