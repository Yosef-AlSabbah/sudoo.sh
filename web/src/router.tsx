// Pages load when first opened (one small file each), so the first visit downloads only the frame and the page
// it shows. Each page names the permission it needs; the backend checks it again on every request.

import type { ComponentType } from "react";
import { createBrowserRouter } from "react-router";
import type { Permission } from "./api/types";
import { RequirePermission, RequireSession, Shell } from "./components/Shell";
import { DashboardPage } from "./pages/Dashboard";
import { LoginPage } from "./pages/Login";

function page<M>(load: () => Promise<M>, pick: (module: M) => ComponentType, permission?: Permission) {
  return async () => {
    const Page = pick(await load());
    return {
      Component: permission
        ? () => (
            <RequirePermission permission={permission}>
              <Page />
            </RequirePermission>
          )
        : Page,
    };
  };
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/setup", lazy: page(() => import("./pages/Setup"), (m) => m.SetupPage) },
  {
    element: <RequireSession />,
    children: [
      { path: "/change-password", lazy: page(() => import("./pages/Setup"), (m) => m.ChangePasswordPage) },
      { path: "/setup-second-factor", lazy: page(() => import("./pages/Account"), (m) => m.SetupSecondFactorPage) },
      {
        element: <Shell />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "/i/:name/:tab?", lazy: page(() => import("./pages/Instance"), (m) => m.InstancePage) },
          { path: "/new", lazy: page(() => import("./pages/NewInstance"), (m) => m.NewInstancePage, "instances.create") },
          { path: "/settings", lazy: page(() => import("./pages/Settings"), (m) => m.SettingsPage, "settings.manage") },
          { path: "/plugins/:tab?", lazy: page(() => import("./pages/Plugins"), (m) => m.PluginsPage, "plugins.view") },
          { path: "/accounts", lazy: page(() => import("./pages/Accounts"), (m) => m.AccountsPage, "accounts.manage") },
          { path: "/tokens", lazy: page(() => import("./pages/Tokens"), (m) => m.TokensPage, "tokens.manage") },
          { path: "/backups", lazy: page(() => import("./pages/Backups"), (m) => m.BackupsPage, "backups.manage") },
          { path: "/activity", lazy: page(() => import("./pages/Audit"), (m) => m.AuditPage, "audit.view") },
          { path: "/github", lazy: page(() => import("./pages/GitHub"), (m) => m.GitHubPage, "github.manage") },
          { path: "/account", lazy: page(() => import("./pages/Account"), (m) => m.AccountPage) },
          { path: "/help/*", lazy: page(() => import("./pages/Help"), (m) => m.HelpPage) },
          { path: "*", lazy: page(() => import("./pages/NotFound"), (m) => m.NotFoundPage) },
        ],
      },
    ],
  },
]);
