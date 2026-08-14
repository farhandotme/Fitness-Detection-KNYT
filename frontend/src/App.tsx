import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/not-found";
import { Route, Switch, Router as WouterRouter } from "wouter";

import { HomePage } from "@/pages/HomePage";
import { ExercisePage } from "@/pages/ExercisePage";
import { SessionPage } from "@/pages/SessionPage";
import { EventsPage } from "@/pages/events/EventsPage";
import { EventJoinPage } from "@/pages/events/EventJoinPage";
import { RoomsLobbyPage } from "@/pages/events/RoomsLobbyPage";
import { WaitingRoomPage } from "@/pages/events/WaitingRoomPage";
import { CompetitionPlayPage } from "@/pages/events/CompetitionPlayPage";
import { CompetitionResultsPage } from "@/pages/events/CompetitionResultsPage";
import { AdminLoginPage } from "@/pages/admin/AdminLoginPage";
import { AdminDashboardPage } from "@/pages/admin/AdminDashboardPage";
import { AdminEventRoomsPage } from "@/pages/admin/AdminEventRoomsPage";
import { AdminLiveRoomPage } from "@/pages/admin/AdminLiveRoomPage";

const queryClient = new QueryClient();

function Router() {
  return (
    <Switch>
      <Route path="/" component={HomePage} />
      <Route path="/exercise/:id" component={ExercisePage} />
      <Route path="/exercise/:id/session" component={SessionPage} />

      {/* Competition platform - built around the existing exercise engine above */}
      <Route path="/events" component={EventsPage} />
      <Route path="/events/:eventId" component={EventJoinPage} />
      <Route path="/events/:eventId/rooms" component={RoomsLobbyPage} />
      <Route path="/competitions/:competitionId/waiting" component={WaitingRoomPage} />
      <Route path="/competitions/:competitionId/play" component={CompetitionPlayPage} />
      <Route path="/competitions/:competitionId/results" component={CompetitionResultsPage} />

      {/* Admin - create/manage events. No relation to the anonymous participant flow above. */}
      <Route path="/admin/login" component={AdminLoginPage} />
      <Route path="/admin" component={AdminDashboardPage} />
      <Route path="/admin/events/:eventId" component={AdminEventRoomsPage} />
      <Route path="/admin/rooms/:competitionId" component={AdminLiveRoomPage} />

      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
