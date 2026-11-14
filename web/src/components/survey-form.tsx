import { useNavigate } from "@tanstack/react-router";
import { cn } from "cn";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";

import type { LikedPerfume, OptionsResponse, PerfumeHit, Preferences, WardrobeRelation } from "@/api";
import { emptyPreferences, searchPerfumes } from "@/api";
import { ChoiceGroup, SearchMultiSelect } from "@/components/choice-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { genderLabel } from "@/labels";

type StepKey = "brands" | "genders" | "liked";

type Step = {
  key: StepKey;
  label: string;
  title: string;
  hint: string;
  placeholder?: string;
};

const STEPS: Step[] = [
  {
    key: "brands",
    label: "Marcas",
    title: "¿Qué marcas te gustan?",
    hint: "Elegí todas las que quieras.",
    placeholder: "Buscar una marca",
  },
  {
    key: "genders",
    label: "Para quién",
    title: "¿Para quién los preferís?",
    hint: "Podés marcar más de una.",
  },
  {
    key: "liked",
    label: "Perfumes",
    title: "Selecciona los perfumes que te hayan gustado",
    hint: "Buscalos por nombre o marca.",
    placeholder: "Buscar un perfume",
  },
];

const RELATIONS: { value: WardrobeRelation; label: string }[] = [
  { value: "have", label: "Lo tengo" },
  { value: "want", label: "Lo quiero" },
  { value: "had", label: "Lo tuve" },
];

type SurveyFormProps = {
  options: OptionsResponse;
  onSubmit: (preferences: Preferences) => void;
};

export function SurveyForm({ options, onSubmit }: SurveyFormProps) {
  const navigate = useNavigate();
  const [preferences, setPreferences] = useState<Preferences>(emptyPreferences);
  const [stepIndex, setStepIndex] = useState(0);
  const [reached, setReached] = useState(0);
  const step = STEPS[stepIndex];
  const stepKey = step.key;
  const last = stepIndex === STEPS.length - 1;

  function goTo(index: number) {
    if (index < 0 || index > reached) {
      return;
    }
    setStepIndex(index);
  }

  function next() {
    if (last) {
      onSubmit(preferences);
      return;
    }
    const following = stepIndex + 1;
    setReached((current) => Math.max(current, following));
    setStepIndex(following);
  }

  function update(key: Exclude<StepKey, "liked">, values: string[]) {
    setPreferences((current) => ({ ...current, [key]: values }));
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <nav aria-label="Pasos de la encuesta">
        <ol className="grid grid-cols-3">
          {STEPS.map((item, index) => {
            const current = index === stepIndex;
            const done = index < stepIndex;
            const open = index <= reached;
            return (
              <li key={item.key} className="relative flex flex-col items-center gap-2">
                {index < STEPS.length - 1 ? (
                  <span
                    className={cn(
                      "absolute top-[13px] left-1/2 h-px w-full",
                      index < stepIndex ? "bg-foreground" : "bg-border",
                    )}
                  />
                ) : null}
                <button
                  type="button"
                  disabled={!open}
                  aria-current={current ? "step" : undefined}
                  className="relative z-10 flex flex-col items-center gap-2 disabled:cursor-not-allowed"
                  onClick={() => goTo(index)}
                >
                  <span
                    className={cn(
                      "flex size-7 items-center justify-center rounded-full border text-xs",
                      current && "border-foreground bg-foreground text-background",
                      done && "border-foreground bg-foreground text-background",
                      !current && !done && open && "border-foreground bg-background",
                      !open && "border-border bg-background text-muted-foreground",
                    )}
                  >
                    {done ? <Check className="size-3.5" /> : index + 1}
                  </span>
                  <span
                    className={cn(
                      "text-center text-xs",
                      current ? "font-medium" : "text-muted-foreground",
                    )}
                  >
                    {item.label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
      <Card className="flex w-full flex-col overflow-visible">
        <CardHeader>
          <CardTitle className="min-h-12">{step.title}</CardTitle>
          <CardDescription className="min-h-10">
            Paso {stepIndex + 1} de {STEPS.length}. {step.hint}
          </CardDescription>
        </CardHeader>
        <CardContent className="min-h-40">
          {stepKey === "liked" ? (
            <LikedPicker
              liked={preferences.liked}
              onChange={(liked) => setPreferences((current) => ({ ...current, liked }))}
            />
          ) : stepKey === "genders" ? (
            <ChoiceGroup
              options={options.genders.map((gender) => ({
                value: gender,
                label: genderLabel(gender),
              }))}
              selected={preferences.genders}
              onChange={(genders) => update("genders", genders)}
            />
          ) : (
            <SearchMultiSelect
              key={stepKey}
              placeholder={step.placeholder ?? "Buscar"}
              options={optionsFor(stepKey, options)}
              selected={preferences[stepKey]}
              onChange={(values) => update(stepKey, values)}
            />
          )}
        </CardContent>
        <CardFooter className="justify-between">
          {stepIndex === 0 ? (
            <Button type="button" variant="ghost" onClick={() => void navigate({ to: "/" })}>
              Inicio
            </Button>
          ) : (
            <Button type="button" variant="ghost" onClick={() => goTo(stepIndex - 1)}>
              Atrás
            </Button>
          )}
          <Button type="button" onClick={next}>
            {last ? "Ver recomendaciones" : "Siguiente"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

function LikedPicker({
  liked,
  onChange,
}: {
  liked: LikedPerfume[];
  onChange: (liked: LikedPerfume[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<PerfumeHit[]>([]);

  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setMatches([]);
      return;
    }
    const timer = window.setTimeout(() => {
      void searchPerfumes(needle)
        .then(setMatches)
        .catch(() => setMatches([]));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  function add(hit: PerfumeHit) {
    if (liked.some((item) => item.perfume_id === hit.perfume_id) || liked.length >= 5) {
      return;
    }
    onChange([
      { perfume_id: hit.perfume_id, name: hit.name, brand: hit.brand, relation: "have" },
      ...liked,
    ]);
    setQuery("");
    setMatches([]);
  }

  function setRelation(perfumeId: number, relation: WardrobeRelation) {
    onChange(liked.map((item) => (item.perfume_id === perfumeId ? { ...item, relation } : item)));
  }

  return (
    <div className="flex flex-col gap-4">
      <Input
        value={query}
        placeholder="Buscar un perfume o una marca"
        disabled={liked.length >= 5}
        onChange={(event) => setQuery(event.target.value)}
      />
      {matches.length > 0 ? (
        <ul className="overflow-hidden rounded-lg border">
          {matches.map((hit) => (
            <li key={hit.perfume_id}>
              <button
                type="button"
                className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => add(hit)}
              >
                <span>{hit.name}</span>
                <span className="text-muted-foreground">{hit.brand}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="flex flex-col gap-3">
        {liked.map((item) => (
          <li key={item.perfume_id} className="rounded-lg border p-3">
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <span className="text-sm font-medium">{item.name}</span>
              <button
                type="button"
                className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => onChange(liked.filter((current) => current.perfume_id !== item.perfume_id))}
              >
                Quitar
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {RELATIONS.map((relation) => (
                <button
                  key={relation.value}
                  type="button"
                  aria-pressed={item.relation === relation.value}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs",
                    item.relation === relation.value
                      ? "border-foreground bg-foreground text-background"
                      : "border-border",
                  )}
                  onClick={() => setRelation(item.perfume_id, relation.value)}
                >
                  {relation.label}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function optionsFor(key: Exclude<StepKey, "genders" | "liked">, options: OptionsResponse) {
  const values = options[key];
  return values.map((value) => ({ value, label: value }));
}
