import { useQuery } from "@tanstack/react-query";
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCommunityRating, genderLabel } from "./labels";
import { loadSurvey, saveSurvey } from "./preferences";
import { RatingSelect } from "./RatingSelect";
import { loadRatings, mergeRatings, saveRatings } from "./ratings";

function Photo({ src, name }: { src: string; name: string }) {
  const [failed, setFailed] = useState(false);
  const frame = "flex h-52 w-full shrink-0 items-center justify-center bg-white p-4";
  if (!src || failed) {
    return (
      <div className={`${frame} text-center text-xs text-muted-foreground`}>Sin foto</div>
    );
  }
  return (
    <div className={frame}>
      <img
        src={src}
        alt={`Foto de ${name}`}
        className="h-full w-full object-contain"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

const NOTE_LEVELS = [
  { level: "top", label: "Salida" },
  { level: "middle", label: "Corazón" },
  { level: "base", label: "Fondo" },
  { level: "single", label: "Notas" },
] as const;

function Notes({ notes }: { notes: Perfume["notes"] }) {
  const rows = NOTE_LEVELS.flatMap((row) => {
    const value = notes
      .filter((note) => note.level === row.level)
      .map((note) => note.name)
      .join(", ");
    return value ? [{ label: row.label, value }] : [];
  });
  if (rows.length === 0) {
    return null;
  }
  return (
    <>
      {rows.map((row) => (
        <Attribute key={row.label} label={row.label} value={row.value} />
      ))}
    </>
  );
}

function Attribute({ label, value }: { label: string; value: string }) {
  if (!value) {
    return null;
  }
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{value}</dd>
    </>
  );
}

const RELATIONS = [
  { value: "have", label: "Lo tengo", badge: "border-transparent bg-[#7c2f38] text-[#f6f1ea]", edge: "border-l-[#7c2f38]" },
  { value: "want", label: "Lo quiero", badge: "border-transparent bg-[#a6844a] text-[#f6f1ea]", edge: "border-l-[#a6844a]" },
  { value: "had", label: "Lo tuve", badge: "border-transparent bg-[#6f675f] text-[#f6f1ea]", edge: "border-l-[#6f675f]" },
] as const;

function relationStyle(relation: Perfume["relation"]) {
  return RELATIONS.find((item) => item.value === relation) ?? null;
}

function PerfumeFacts({ perfume }: { perfume: Perfume }) {
  return (
    <dl className="grid grid-cols-[4.75rem_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-sm leading-snug">
      <Attribute label="Marca" value={perfume.brand} />
      <Attribute label="Género" value={genderLabel(perfume.gender)} />
      <Attribute label="Familia" value={perfume.olfactive_family} />
      <Notes notes={perfume.notes ?? []} />
      <Attribute
        label="Año"
        value={perfume.launch_year == null ? "" : String(perfume.launch_year)}
      />
      <Attribute
        label="Rating"
        value={formatCommunityRating(perfume.rating_value, perfume.rating_count)}
      />
    </dl>
  );
}

function PerfumeProfile({ perfume }: { perfume: Perfume }) {
  return (
    <Sheet>
      <SheetTrigger className="self-start text-xs font-medium underline-offset-4 hover:underline">
        Ver ficha
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader className="pr-10">
          <SheetTitle>{perfume.name}</SheetTitle>
          <SheetDescription>{perfume.brand}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-4 px-4 pb-6">
          <Photo src={perfume.image_url} name={perfume.name} />
          <PerfumeFacts perfume={perfume} />
          {perfume.description ? (
            <p className="text-sm leading-relaxed text-muted-foreground">{perfume.description}</p>
          ) : (
            <p className="text-sm text-muted-foreground">Este perfume no tiene descripción.</p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function PerfumeCard({
  perfume,
  draft,
  onDraft,
  showRating,
}: {
  perfume: Perfume;
  draft: string | null;
  onDraft: (value: string | null) => void;
  showRating: boolean;
}) {
  const relation = relationStyle(perfume.relation);
  return (
    <Card className={`h-full gap-0 overflow-hidden border-l-4 py-0 ${relation ? relation.edge : "border-l-transparent"}`}>
      <Photo src={perfume.image_url} name={perfume.name} />
      <div className="flex min-w-0 flex-1 flex-col gap-2 py-3">
        <CardHeader className="px-4">
          {relation ? (
            <Badge className={`mb-2 ${relation.badge}`}>{relation.label}</Badge>
          ) : null}
          <CardTitle className="line-clamp-2 min-h-10">{perfume.name}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col gap-2 px-4">
          <PerfumeFacts perfume={perfume} />
          <p className="mt-auto line-clamp-4 min-h-[4.875rem] text-xs leading-relaxed text-muted-foreground">
            {perfume.description}
          </p>
          <PerfumeProfile perfume={perfume} />
        </CardContent>
      </div>
      {showRating ? (
        <CardFooter className="justify-end">
          <RatingSelect value={draft} onChange={onDraft} />
        </CardFooter>
      ) : null}
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

function tabCopy(tab: Exclude<Tab, "wardrobe">): string {
  if (tab === "para_vos") {
    return "Recomendaciones para este perfil.";
  }
  if (tab === "trending") {
    return "Los que más interacciones tuvieron en el último año, con un rating de al menos ok.";
  }
  if (tab === "mejor_puntuados") {
    return "Los de mejor rating entre los que tienen más votos que la mayoría del catálogo.";
  }
  return "Los más votados, con un rating de al menos ok.";
}

function useProfile(route: "/recomendar/$username" | "/wardrobe/$username") {
  const { username } = useParams({ from: route });
  const navigate = useNavigate();
  const session = useQuery({
    queryKey: ["sesion", username],
    queryFn: () => openSession(username),
  });
  const slug = session.data?.username ?? username;
  const stored = useMemo(
    () => (session.data && !session.data.conocido ? loadSurvey(session.data.username) : null),
    [session.data],
  );

  useEffect(() => {
    if (!session.data) {
      return;
    }
    if (session.data.username !== username) {
      void navigate({
        to: route,
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
  }, [session.data, username, navigate, route]);

  const ready = Boolean(session.data && (session.data.conocido || stored));
  return { slug, session, stored, ready };
}

function RecommendPage() {
  const { slug, session, stored, ready } = useProfile("/recomendar/$username");
  const [tab, setTab] = useState<Exclude<Tab, "wardrobe">>("para_vos");
  const [submitted, setSubmitted] = useState(() => loadRatings(slug));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const query = useQuery({
    queryKey: ["recomendaciones", slug, tab, submitted, stored],
    queryFn: () => fetchRecommendations(slug, tab, submitted, stored ?? emptyPreferences()),
    enabled: ready,
  });

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

  return (
    <SidebarProvider>
      <AppSidebar
        section="recomendaciones"
        username={slug}
        avatarUrl={session.data?.avatar_url ?? null}
      />
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
            <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
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
            <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
              {query.data.perfumes.map((perfume) => (
                <PerfumeCard
                  key={perfume.perfume_id}
                  perfume={perfume}
                  draft={drafts[String(perfume.perfume_id)] ?? null}
                  showRating
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

function WardrobePage() {
  const { slug, session, stored, ready } = useProfile("/wardrobe/$username");
  const query = useQuery({
    queryKey: ["recomendaciones", slug, "wardrobe", stored],
    queryFn: () => fetchRecommendations(slug, "wardrobe", [], stored ?? emptyPreferences()),
    enabled: ready,
  });

  return (
    <SidebarProvider>
      <AppSidebar section="wardrobe" username={slug} avatarUrl={session.data?.avatar_url ?? null} />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <h1 className="font-heading text-lg font-semibold">Wardrobe</h1>
        </header>
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-6 py-6">
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
            <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} className="h-72 rounded-xl" />
              ))}
            </div>
          ) : null}
          {query.isError ? (
            <Alert variant="destructive">
              <AlertTitle>No se pudo cargar el wardrobe</AlertTitle>
              <AlertDescription>
                {query.error instanceof Error ? query.error.message : "Probá de nuevo en un momento."}
              </AlertDescription>
            </Alert>
          ) : null}
          {query.data && query.data.perfumes.length === 0 ? (
            <Alert>
              <AlertTitle>Wardrobe vacío</AlertTitle>
              <AlertDescription>No hay perfumes guardados para este perfil.</AlertDescription>
            </Alert>
          ) : null}
          {query.data && query.data.perfumes.length > 0 ? (
            <div className="flex flex-col gap-8">
              {[...RELATIONS, { value: null, label: "Sin relación", badge: "", edge: "" }].map((group) => {
                const perfumes = query.data.perfumes.filter((perfume) =>
                  group.value === null ? !relationStyle(perfume.relation) : perfume.relation === group.value,
                );
                if (perfumes.length === 0) {
                  return null;
                }
                return (
                  <section key={group.value}>
                    <h2 className="mb-3 flex items-center gap-2 font-heading text-base font-semibold">
                      <Badge className={group.badge}>{group.label}</Badge>
                      <span className="text-sm font-normal text-muted-foreground">{perfumes.length}</span>
                    </h2>
                    <div className="grid grid-cols-1 items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {perfumes.map((perfume) => (
                        <PerfumeCard
                          key={perfume.perfume_id}
                          perfume={perfume}
                          draft={null}
                          showRating={false}
                          onDraft={() => undefined}
                        />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          ) : null}
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

const wardrobeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/wardrobe/$username",
  component: WardrobePage,
});

const routeTree = rootRoute.addChildren([indexRoute, surveyRoute, recommendRoute, wardrobeRoute]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
