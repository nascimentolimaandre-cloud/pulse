import { create } from 'zustand';

interface User {
  id: string;
  name: string;
  email: string;
  organizationId: string;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
}

interface AuthActions {
  setUser: (user: User | null) => void;
}

interface AuthStore extends AuthState, AuthActions {}

/**
 * MVP: No auth flow. isAuthenticated is always true.
 * Default tenant is loaded from environment.
 */
export const useAuthStore = create<AuthStore>()((set) => ({
  user: null,
  isAuthenticated: true,

  setUser: (user: User | null) => set({ user }),
}));
