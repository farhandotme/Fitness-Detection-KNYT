import React, { useState } from 'react';
import { Link } from 'wouter';
import { exercises, ExerciseCategory } from '@/config/exercises';
import { cn } from '@/lib/utils';
import { Settings, Dumbbell, Activity, ShieldCheck, Flame, Timer, ActivitySquare, ArrowUpRight, Sparkles, Search } from 'lucide-react';

const CATEGORIES: { id: ExerciseCategory | "all"; label: string; icon: React.ReactNode }[] = [
  { id: "all", label: "All", icon: <Dumbbell className="w-4 h-4" /> },
  { id: "upper_body", label: "Upper Body", icon: <ActivitySquare className="w-4 h-4" /> },
  { id: "lower_body", label: "Lower Body", icon: <ShieldCheck className="w-4 h-4" /> },
  { id: "core", label: "Core", icon: <Activity className="w-4 h-4" /> },
  { id: "cardio", label: "Cardio", icon: <Flame className="w-4 h-4" /> },
  { id: "mobility", label: "Mobility", icon: <Timer className="w-4 h-4" /> },
  { id: "full_body", label: "Full Body", icon: <Dumbbell className="w-4 h-4" /> },
];

export function HomePage() {
  const [activeCategory, setActiveCategory] = useState<ExerciseCategory | "all">("all");
  const [searchTerm, setSearchTerm] = useState('');
  const [wsOverride, setWsOverride] = useState(localStorage.getItem('WS_BASE_OVERRIDE') || '');
  const [showSettings, setShowSettings] = useState(false);

  const normalizedSearch = searchTerm.trim().toLowerCase();
  const filteredExercises = exercises.filter(e => {
    const matchesCategory = activeCategory === "all" || e.category === activeCategory;
    const matchesSearch = !normalizedSearch || [e.name, e.tagline, e.category, e.difficulty].some(value =>
      value.toLowerCase().includes(normalizedSearch),
    );
    return matchesCategory && matchesSearch;
  });

  const saveWsOverride = () => {
    if (wsOverride) {
      localStorage.setItem('WS_BASE_OVERRIDE', wsOverride);
    } else {
      localStorage.removeItem('WS_BASE_OVERRIDE');
    }
    setShowSettings(false);
  };

  return (
    <div className="min-h-[100dvh] bg-background text-foreground pb-20">
      {/* Header */}
       <header className="sticky top-0 z-50 bg-background/80 backdrop-blur-xl border-b border-border p-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary rounded-2xl flex items-center justify-center text-primary-foreground font-black text-xl shadow-lg shadow-primary/20">
              <Activity className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold uppercase tracking-tight leading-none">Fitness Coach</h1>
              <p className="text-xs text-muted-foreground uppercase tracking-widest">Real-time Form Tracking</p>
            </div>
          </div>
          <button 
            onClick={() => setShowSettings(!showSettings)}
               data-testid="button-settings"
               className="p-2.5 bg-secondary/70 hover:bg-secondary rounded-full transition-colors"
          >
            <Settings className="w-5 h-5 text-muted-foreground" />
          </button>
        </div>
      </header>

      {/* Settings Panel */}
      {showSettings && (
        <div className="max-w-6xl mx-auto p-4 animate-in fade-in slide-in-from-top-4 duration-200">
          <div className="bg-card border border-card-border p-4 rounded-xl flex flex-col gap-3">
            <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">Connection Settings</h3>
            <div className="flex gap-2">
              <input 
                type="text" 
                value={wsOverride}
                onChange={(e) => setWsOverride(e.target.value)}
                placeholder="ws://localhost:8000"
                className="flex-1 bg-background border border-input rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary font-mono"
              />
              <button 
                onClick={saveWsOverride}
                className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-bold uppercase tracking-wider hover:brightness-110 transition-all"
              >
                Save
              </button>
            </div>
            <p className="text-xs text-muted-foreground">Override the WebSocket server URL. Leave blank to use default.</p>
          </div>
        </div>
      )}

        <main className="max-w-6xl mx-auto p-4 mt-6 flex flex-col gap-7">
          <section className="relative overflow-hidden rounded-[2rem] bg-[#0d2028] p-7 md:p-10 text-[#f4f7f2] shadow-2xl shadow-black/25 border border-primary/15">
            <div className="absolute -right-16 -top-24 h-72 w-72 rounded-full border-[42px] border-primary/15 ambient-pulse" />
            <div className="absolute right-10 bottom-[-80px] h-48 w-48 rounded-full border-[26px] border-accent/20 ambient-pulse" />
           <div className="relative max-w-xl">
              <div className="flex items-center gap-2 text-accent text-xs uppercase tracking-[.22em] font-bold"><Sparkles className="w-4 h-4" /> Focused movement</div>
             <h2 className="font-display text-4xl md:text-6xl font-extrabold tracking-[-.05em] leading-[.95] mt-5">Move with<br />quiet confidence.</h2>
              <p className="mt-5 text-sm md:text-base text-slate-300 max-w-md leading-relaxed">A precise coach for the work in front of you. Choose an exercise, set your pace, and let your form do the talking.</p>
           </div>
         </section>

          <section className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-[.24em] text-primary">Exercise library</p>
              <div className="mt-2 flex items-baseline gap-3">
                <h2 className="font-display text-2xl font-extrabold tracking-tight">Choose your work</h2>
                <span className="rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 font-mono text-xs text-primary">
                  {exercises.length} total
                </span>
              </div>
            </div>
            <label className="relative block w-full md:max-w-sm">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                type="search"
                placeholder="Search exercises..."
                aria-label="Search exercises"
                className="h-12 w-full rounded-2xl border border-border bg-card/80 pl-11 pr-4 text-sm text-foreground outline-none transition placeholder:text-muted-foreground focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
              />
            </label>
          </section>
        
        {/* Categories */}
        <div className="flex overflow-x-auto gap-2 pb-2 custom-scrollbar -mx-4 px-4 md:mx-0 md:px-0">
          {CATEGORIES.map(cat => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-full text-sm font-bold uppercase tracking-wider whitespace-nowrap transition-all",
                activeCategory === cat.id 
                  ? "bg-foreground text-background shadow-lg" 
                  : "bg-secondary text-muted-foreground hover:bg-secondary/80"
              )}
            >
              {cat.icon}
              {cat.label}
            </button>
          ))}
        </div>

        {/* Grid */}
         <div className="flex items-center justify-between text-xs text-muted-foreground">
           <span>{filteredExercises.length} {filteredExercises.length === 1 ? 'exercise' : 'exercises'} shown</span>
           {searchTerm && <button onClick={() => setSearchTerm('')} className="text-primary hover:text-primary/80">Clear search</button>}
         </div>

         <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredExercises.map(ex => (
            <Link key={ex.id} href={`/exercise/${ex.id}`} className="group block">
               <div data-testid={`card-exercise-${ex.id}`} className="bg-card border border-card-border rounded-[1.5rem] p-5 h-full min-h-[245px] transition-all duration-300 hover:border-primary/50 hover:-translate-y-1 hover:shadow-xl hover:shadow-primary/10 relative overflow-hidden flex flex-col justify-between">
                
                 <div className="absolute right-0 top-0 z-0 h-36 w-44 overflow-hidden rounded-bl-[4rem] bg-gradient-to-br from-primary/15 via-accent/10 to-transparent">
                   {ex.imageUrl ? (
                     <img src={ex.imageUrl} alt="" className="h-full w-full object-cover opacity-45 mix-blend-multiply transition-opacity duration-300 group-hover:opacity-65" />
                   ) : (
                   <Activity className="absolute right-7 top-7 h-16 w-16 -rotate-12 text-primary/20 transition-transform duration-500 group-hover:rotate-0 group-hover:scale-110" />
                   )}
                 </div>
                
                {/* Mode Badge */}
                <div className="absolute top-4 right-4 z-10">
                  <span className={cn(
                    "px-2.5 py-1 text-[10px] font-black uppercase tracking-widest rounded-md",
                    ex.mode === 'reps' ? "bg-accent/20 text-accent" : "bg-primary/20 text-primary"
                  )}>
                    {ex.mode}
                  </span>
                </div>

                <div className="mb-8">
                   <div className="w-12 h-1 rounded-full bg-accent mb-7 transition-all group-hover:w-20" />
                  <h2 className="text-2xl font-bold tracking-tight mb-1 group-hover:text-primary transition-colors">{ex.name}</h2>
                  <p className="text-sm text-muted-foreground line-clamp-2">{ex.tagline}</p>
                </div>
                   <ArrowUpRight className="absolute right-5 bottom-5 w-5 h-5 text-muted-foreground group-hover:text-primary transition-colors" />

                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground bg-secondary px-2.5 py-1 rounded-md">
                    {ex.difficulty}
                  </span>
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground bg-secondary px-2.5 py-1 rounded-md">
                    {ex.category.replace('_', ' ')}
                  </span>
                </div>

              </div>
            </Link>
          ))}
        </div>

      </main>
    </div>
  );
}
