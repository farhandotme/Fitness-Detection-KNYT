import { NavLink, Outlet } from "react-router-dom";

function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <span className="wordmark">
          KNYT<span className="wordmark-accent">.FIT</span>
        </span>

        <nav className="nav-pills">
          <NavLink
            to="/exercises"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            🔍 Exercises
          </NavLink>
          <NavLink
            to="/body-scan"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            Body Scan
          </NavLink>
        </nav>
      </header>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

export default Layout;
