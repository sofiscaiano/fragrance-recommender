import { cn } from "cn";
import { Check } from "lucide-react";
import { useState } from "react";

import type { OptionsResponse, Preferences } from "@/api";
import { emptyPreferences } from "@/api";
import { ChoiceGroup, SearchMultiSelect } from "@/components/choice-picker";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { genderLabel } from "@/labels";

type StepKey = keyof Preferences;

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
    hint: "Elegí todas las que quieras. Si no elegís ninguna, esta pregunta no filtra.",
    placeholder: "Buscar una marca",
  },
  {
    key: "genders",
    label: "Para quién",
    title: "¿Para quién los preferís?",
    hint: "Podés marcar más de una. Si no marcás ninguna, no filtramos por esto.",
  },
  {
    key: "perfumers",
    label: "Perfumistas",
    title: "¿Tenés perfumistas favoritos?",
    hint: "Elegí todos los que quieras. Si no elegís ninguno, esta pregunta no filtra.",
    placeholder: "Buscar un perfumista",
  },
  {
    key: "families",
    label: "Familias",
    title: "¿Alguna familia olfativa?",
    hint: "Elegí todas las que quieras. Si no elegís ninguna, esta pregunta no filtra.",
    placeholder: "Buscar una familia",
  },
];

type SurveyFormProps = {
  options: OptionsResponse;
  onSubmit: (preferences: Preferences) => void;
};

export function SurveyForm({ options, onSubmit }: SurveyFormProps) {
  const [preferences, setPreferences] = useState<Preferences>(emptyPreferences);
  const [stepIndex, setStepIndex] = useState(0);
  const [reached, setReached] = useState(0);
  const step = STEPS[stepIndex];
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

  function update(key: StepKey, values: string[]) {
    setPreferences((current) => ({ ...current, [key]: values }));
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <nav aria-label="Pasos de la encuesta">
        <ol className="grid grid-cols-4">
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
      <Card className="w-full overflow-visible">
        <CardHeader>
          <CardTitle>{step.title}</CardTitle>
          <CardDescription>
            Paso {stepIndex + 1} de {STEPS.length}. {step.hint}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {step.key === "genders" ? (
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
              key={step.key}
              placeholder={step.placeholder ?? "Buscar"}
              options={optionsFor(step.key, options)}
              selected={preferences[step.key]}
              onChange={(values) => update(step.key, values)}
            />
          )}
        </CardContent>
        <CardFooter className="justify-between">
          <Button
            type="button"
            variant="ghost"
            disabled={stepIndex === 0}
            onClick={() => goTo(stepIndex - 1)}
          >
            Atrás
          </Button>
          <Button type="button" onClick={next}>
            {last ? "Ver recomendaciones" : "Siguiente"}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

function optionsFor(key: Exclude<StepKey, "genders">, options: OptionsResponse) {
  const values = options[key];
  return values.map((value) => ({ value, label: value }));
}
