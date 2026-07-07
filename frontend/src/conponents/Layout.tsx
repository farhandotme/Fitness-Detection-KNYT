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
            to="/fingers"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            Fingers
          </NavLink>
          <NavLink
            to="/reps"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            Reps
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
