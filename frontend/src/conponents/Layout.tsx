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
            Bicep
          </NavLink>
          <NavLink
            to="/squat"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            Squat
          </NavLink>
          <NavLink
            to="/pushup"
            className={({ isActive }) => `nav-pill ${isActive ? "active" : ""}`}
          >
            Push-ups
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
