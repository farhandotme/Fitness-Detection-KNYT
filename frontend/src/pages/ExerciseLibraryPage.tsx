import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CATEGORIES,
  EXERCISES,
  matchesQuery,
  type ExerciseCategory,
} from "../data/exercises";
import "./ExerciseLibraryPage.css";

function ExerciseLibraryPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<
    ExerciseCategory | "All"
  >("All");

  const results = useMemo(() => {
    return EXERCISES.filter((ex) => {
      const categoryOk =
        activeCategory === "All" || ex.category === activeCategory;
      return categoryOk && matchesQuery(ex, query);
    });
  }, [query, activeCategory]);

  const availableCount = results.filter((r) => r.status === "available").length;

  return (
    <div className="library-page">
      <div className="library-header">
        <h1 className="bicep-title">Exercise Library</h1>
        <p className="library-subtitle">
          Search any exercise — the catalog is growing toward 1,000+. Tracked
          exercises open a live camera session; the rest are on the way.
        </p>
      </div>

      <div className="library-search-row">
        <div className="library-search-box">
          <span className="library-search-icon">🔍</span>
          <input
            autoFocus
            type="text"
            className="library-search-input"
            placeholder="Search exercises — e.g. “jumping jacks”, “core”, “dumbbell”…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              className="library-search-clear"
              onClick={() => setQuery("")}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="library-filter-row">
        <button
          className={`library-chip ${activeCategory === "All" ? "active" : ""}`}
          onClick={() => setActiveCategory("All")}
        >
          All
        </button>
        {CATEGORIES.map((c) => (
          <button
            key={c}
            className={`library-chip ${activeCategory === c ? "active" : ""}`}
            onClick={() => setActiveCategory(c)}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="library-result-count">
        {results.length} exercise{results.length === 1 ? "" : "s"} found
        {availableCount > 0 && (
          <span className="library-result-count-live">
            {" "}
            · {availableCount} ready to track now
          </span>
        )}
      </div>

      <div className="library-grid">
        {results.map((ex) => {
          const isAvailable = ex.status === "available";
          return (
            <button
              key={ex.id}
              className={`library-card ${isAvailable ? "" : "disabled"}`}
              disabled={!isAvailable}
              onClick={() => isAvailable && ex.route && navigate(ex.route)}
            >
              <div className="library-card-top">
                <span className="library-card-emoji">{ex.emoji}</span>
                {isAvailable ? (
                  <span className="library-card-badge live">Live tracking</span>
                ) : (
                  <span className="library-card-badge soon">Coming soon</span>
                )}
              </div>
              <div className="library-card-name">{ex.name}</div>
              <div className="library-card-meta">
                {ex.category} · {ex.equipment} · {ex.difficulty}
              </div>
              <p className="library-card-desc">{ex.description}</p>
            </button>
          );
        })}

        {results.length === 0 && (
          <div className="library-empty">
            No exercises match “{query}”. Try a different search term.
          </div>
        )}
      </div>
    </div>
  );
}

export default ExerciseLibraryPage;
