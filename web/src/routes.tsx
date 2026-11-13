import { useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  useNavigate,
  useParams,
} from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import {
  emptyPreferences,
  fetchOptions,
  fetchRecommendations,
  openSession,
  type Perfume,
  type Tab,
} from "./api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AppSidebar } from "@/components/app-sidebar";
import { LoginForm } from "@/components/login-form";
import { Logo } from "@/components/logo";
import { SurveyForm } from "@/components/survey-form";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCommunityRating, genderLabel } from "./labels";
import { loadSurvey, saveSurvey } from "./preferences";
import { RatingSelect } from "./RatingSelect";
import { loadRatings, mergeRatings, saveRatings } from "./ratings";

function Photo({ src, name }: { src: string; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className="flex aspect-[3/4] w-28 shrink-0 items-center justify-center self-start bg-muted px-2 text-center text-xs text-muted-foreground sm:w-36">
        Sin foto
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={`Foto de ${name}`}
      className="aspect-[3/4] w-28 shrink-0 self-start bg-muted object-cover sm:w-36"
      onError={() => setFailed(true)}
    />
  );
}

function Attribute({ label, value }: { label: string; value: string }) {
  if (!value) {
    return null;
  }
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{value}</dd>
    </div>
  );
}

function PerfumeCard({
  perfume,
  draft,
  onDraft,
}: {
  perfume: Perfume;
  draft: string | null;
  onDraft: (value: string | null) => void;
}) {
  return (
    <Card className="h-full gap-0 py-0">
      <div className="flex min-h-56 flex-1">
        <Photo src={perfume.image_url} name={perfume.name} />
        <div className="flex min-w-0 flex-1 flex-col gap-3 py-4">
          <CardHeader className="px-4">
            <CardTitle className="line-clamp-3">{perfume.name}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-3 px-4">
            <dl className="space-y-1 text-sm">
              <Attribute label="Marca" value={perfume.brand} />
              <Attribute label="Género" value={genderLabel(perfume.gender)} />
              <Attribute label="Perfumista" value={perfume.perfumers.join(", ")} />
              <Attribute label="Familia" value={perfume.olfactive_family} />
              <Attribute
                label="Año"
                value={perfume.launch_year == null ? "" : String(perfume.launch_year)}
              />
              <Attribute
                label="Rating"
                value={formatCommunityRating(perfume.rating_value, perfume.rating_count)}
              />
            </dl>
            {perfume.description ? (
              <p className="line-clamp-4 text-xs text-muted-foreground">{perfume.description}</p>
            ) : null}
          </CardContent>
        </div>
      </div>
      <CardFooter className="justify-end">
        <RatingSelect value={draft} onChange={onDraft} />
      </CardFooter>
    </Card>
  );
}

function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  return (
    <main className="flex min-h-svh w-full items-center justify-center p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col items-center gap-6">
        <Logo />
        <LoginForm
          className="w-full"
          onSubmit={(username) => {
            setPending(true);
            setError(null);
            void openSession(username)
              .then((session) => {
                if (session.conocido) {
                  void navigate({
                    to: "/recomendar/$username",
                    params: { username: session.username },
                  });
                  return;
                }
                void navigate({
                  to: "/encuesta/$username",
                  params: { username: session.username },
                });
              })
              .catch((reason: unknown) => {
                setError(reason instanceof Error ? reason.message : "No se pudo entrar");
                setPending(false);
              });
          }}
        />
        {pending ? <p className="text-sm text-muted-foreground">Buscando el perfil…</p> : null}
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>No se pudo entrar</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </div>
    </main>
  );
}

function SurveyPage() {
  const { username } = useParams({ from: "/encuesta/$username" });
  const navigate = useNavigate();
  const session = useQuery({
    queryKey: ["sesion", username],
    queryFn: () => openSession(username),
  });
  const options = useQuery({
    queryKey: ["opciones"],
    queryFn: fetchOptions,
  });

  useEffect(() => {
    if (!session.data) {
      return;
    }
    if (session.data.username !== username) {
      void navigate({
        to: "/encuesta/$username",
        params: { username: session.data.username },
        replace: true,
      });
      return;
    }
    if (session.data.conocido) {
      void navigate({
        to: "/recomendar/$username",
        params: { username: session.data.username },
        replace: true,
      });
    }
  }, [session.data, username, navigate]);

  return (
    <main className="flex min-h-svh w-full justify-center px-6 pt-16 pb-10 md:px-10 md:pt-24">
      <div className="flex w-full max-w-xl flex-col items-center gap-8">
        <Logo />
        {session.isPending || options.isPending ? (
          <Skeleton className="h-96 w-full rounded-xl" />
        ) : null}
        {session.isError || options.isError ? (
          <Alert variant="destructive">
            <AlertTitle>No se pudo cargar la encuesta</AlertTitle>
            <AlertDescription>
              {session.error instanceof Error
                ? session.error.message
                : options.error instanceof Error
                  ? options.error.message
                  : "Probá de nuevo en un momento."}
            </AlertDescription>
          </Alert>
        ) : null}
        {session.data && !session.data.conocido && options.data ? (
          <SurveyForm
            options={options.data}
            onSubmit={(preferences) => {
              const name = session.data?.username ?? username;
              saveSurvey(name, preferences);
              void navigate({
                to: "/recomendar/$username",
                params: { username: name },
              });
            }}
          />
        ) : null}
      </div>
    </main>
  );
}

function tabCopy(tab: Tab): string {
  if (tab === "para_vos") {
    return "El orden del modelo, con tu historial. Si puntuás un perfume, entra a ese historial y la lista se vuelve a armar, sin mostrarlo.";
  }
  if (tab === "trending") {
    return "Los que más interacciones tuvieron en el último año, con un rating de al menos ok.";
  }
  if (tab === "mejor_puntuados") {
    return "Los de mejor rating entre los que tienen más votos que la mayoría del catálogo.";
  }
  return "Los más votados, con un rating de al menos ok.";
}

function RecommendPage() {
  const { username } = useParams({ from: "/recomendar/$username" });
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("para_vos");
  const [submitted, setSubmitted] = useState(() => loadRatings(username));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const session = useQuery({
    queryKey: ["sesion", username],
    queryFn: () => openSession(username),
  });
  const slug = session.data?.username ?? username;
  const stored = useMemo(
    () => (session.data && !session.data.conocido ? loadSurvey(session.data.username) : null),
    [session.data],
  );
  const ready = Boolean(session.data && (session.data.conocido || stored));
  const query = useQuery({
    queryKey: ["recomendaciones", slug, tab, submitted, stored],
    queryFn: () => fetchRecommendations(slug, tab, submitted, stored ?? emptyPreferences()),
    enabled: ready,
  });

  useEffect(() => {
    if (!session.data) {
      return;
    }
    if (session.data.username !== username) {
      void navigate({
        to: "/recomendar/$username",
        params: { username: session.data.username },
        replace: true,
      });
      return;
    }
    if (!session.data.conocido && loadSurvey(session.data.username) === null) {
      void navigate({
        to: "/encuesta/$username",
        params: { username: session.data.username },
        replace: true,
      });
    }
  }, [session.data, username, navigate]);

  useEffect(() => {
    setSubmitted(loadRatings(slug));
    setDrafts({});
  }, [slug]);

  function onMore() {
    const next = mergeRatings(submitted, drafts);
    saveRatings(slug, next);
    setSubmitted(next);
    setDrafts({});
  }

  const hasDraft = Object.values(drafts).some((value) => Number(value) >= 1);
  const coldStart = query.data ? !query.data.conocido : false;

  return (
    <SidebarProvider>
      <AppSidebar username={slug} avatarUrl={session.data?.avatar_url ?? null} />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <h1 className="font-heading text-lg font-semibold">Recomendaciones</h1>
        </header>
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-6 py-6">
          <div className="mb-4 flex flex-wrap gap-2">
            <Button
              type="button"
              variant={tab === "para_vos" ? "default" : "outline"}
              onClick={() => setTab("para_vos")}
            >
              Para vos
            </Button>
            <Button
              type="button"
              variant={tab === "populares" ? "default" : "outline"}
              onClick={() => setTab("populares")}
            >
              Más populares
            </Button>
            <Button
              type="button"
              variant={tab === "trending" ? "default" : "outline"}
              onClick={() => setTab("trending")}
            >
              Tendencia
            </Button>
            <Button
              type="button"
              variant={tab === "mejor_puntuados" ? "default" : "outline"}
              onClick={() => setTab("mejor_puntuados")}
            >
              Mejor puntuados
            </Button>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">{tabCopy(tab)}</p>
          {coldStart ? (
            <Alert variant="warning" className="mb-4">
              <TriangleAlert />
              <AlertTitle>Perfil nuevo</AlertTitle>
              <AlertDescription>
                {tab === "para_vos"
                  ? "Todavía no hay historial en el dataset. La lista arranca por popularidad del modelo y se rearma con cada puntaje de esta sesión."
                  : "La lista sale de la pestaña y de lo que hayas elegido en la encuesta."}
              </AlertDescription>
            </Alert>
          ) : null}
          {submitted.length > 0 ? (
            <Badge variant="secondary" className="mb-4">
              {submitted.length} puntaje{submitted.length === 1 ? "" : "s"} de esta sesión
            </Badge>
          ) : null}
          {session.isError ? (
            <Alert variant="destructive">
              <AlertTitle>No se pudo cargar el perfil</AlertTitle>
              <AlertDescription>
                {session.error instanceof Error
                  ? session.error.message
                  : "Probá de nuevo en un momento."}
              </AlertDescription>
            </Alert>
          ) : null}
          {!session.isError && query.isPending ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-72 rounded-xl" />
              ))}
            </div>
          ) : null}
          {query.isError ? (
            <Alert variant="destructive">
              <AlertTitle>No se pudieron cargar las recomendaciones</AlertTitle>
              <AlertDescription>
                {query.error instanceof Error
                  ? query.error.message
                  : "Probá de nuevo en un momento."}
              </AlertDescription>
            </Alert>
          ) : null}
          {query.data && query.data.perfumes.length === 0 ? (
            <Alert>
              <AlertTitle>Sin resultados</AlertTitle>
              <AlertDescription>Ningún perfume cumple estos filtros.</AlertDescription>
            </Alert>
          ) : null}
          {query.data && query.data.perfumes.length > 0 ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {query.data.perfumes.map((perfume) => (
                <PerfumeCard
                  key={perfume.perfume_id}
                  perfume={perfume}
                  draft={drafts[String(perfume.perfume_id)] ?? null}
                  onDraft={(value) =>
                    setDrafts((current) => {
                      const next = { ...current };
                      const id = String(perfume.perfume_id);
                      if (value) {
                        next[id] = value;
                      } else {
                        delete next[id];
                      }
                      return next;
                    })
                  }
                />
              ))}
            </div>
          ) : null}
          <div className="mt-4 flex justify-end">
            <Button type="button" disabled={!hasDraft || query.isFetching} onClick={onMore}>
              Más recomendaciones
            </Button>
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: LoginPage,
});

const surveyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/encuesta/$username",
  component: SurveyPage,
});

const recommendRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recomendar/$username",
  component: RecommendPage,
});

const routeTree = rootRoute.addChildren([indexRoute, surveyRoute, recommendRoute]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
