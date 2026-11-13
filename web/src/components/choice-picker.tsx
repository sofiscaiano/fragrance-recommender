import { cn } from "cn";
import { Check, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";

type Option = {
  value: string;
  label: string;
};

type PickerProps = {
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
};

const RESULT_LIMIT = 8;

function toggleValue(selected: string[], value: string): string[] {
  return selected.includes(value)
    ? selected.filter((item) => item !== value)
    : [...selected, value];
}

export function ChoiceGroup({ options, selected, onChange }: PickerProps) {
  return (
    <div className="grid gap-2 sm:grid-cols-3" role="group">
      {options.map((option) => {
        const pressed = selected.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={pressed}
            className={cn(
              "rounded-lg border px-3 py-4 text-sm transition-colors",
              pressed
                ? "border-foreground bg-foreground text-background"
                : "border-border hover:bg-muted",
            )}
            onClick={() => onChange(toggleValue(selected, option.value))}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function SearchMultiSelect({
  options,
  selected,
  onChange,
  placeholder,
}: PickerProps & { placeholder: string }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const labels = useMemo(
    () => new Map(options.map((option) => [option.value, option.label])),
    [options],
  );
  const needle = query.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!needle) {
      return [];
    }
    return options
      .filter((option) => option.label.toLowerCase().includes(needle))
      .slice(0, RESULT_LIMIT);
  }, [needle, options]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  function pick(value: string) {
    onChange(toggleValue(selected, value));
    setQuery("");
    setActive(0);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, Math.max(matches.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
      return;
    }
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const option = matches[active];
      if (option) {
        pick(option.value);
      }
      return;
    }
    if (event.key === "Backspace" && query === "" && selected.length > 0) {
      onChange(selected.slice(0, -1));
    }
  }

  return (
    <div ref={rootRef} className="flex flex-col gap-3">
      <div className="flex min-h-9 flex-wrap content-start gap-1.5">
        {selected.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-1 rounded-full border bg-secondary py-1 pr-1 pl-2.5 text-sm"
            >
              {labels.get(value) ?? value}
              <button
                type="button"
                className="rounded-full p-0.5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`Quitar ${labels.get(value) ?? value}`}
                onClick={() => onChange(selected.filter((item) => item !== value))}
              >
                <X className="size-3.5" />
              </button>
            </span>
        ))}
      </div>
      <div className="relative">
        <input
          role="combobox"
          aria-expanded={open && needle !== ""}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            open && matches[active] ? `${listId}-${active}` : undefined
          }
          autoFocus
          value={query}
          placeholder={placeholder}
          className="h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {open && needle !== "" ? (
          <div
            id={listId}
            role="listbox"
            className="mt-1 max-h-48 overflow-y-auto rounded-lg border bg-popover p-1"
          >
            {matches.length === 0 ? (
              <p className="px-2.5 py-2 text-sm text-muted-foreground">Nada con ese nombre</p>
            ) : null}
            {matches.map((option, index) => {
              const chosen = selected.includes(option.value);
              return (
                <button
                  key={option.value}
                  id={`${listId}-${index}`}
                  type="button"
                  role="option"
                  aria-selected={chosen}
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-sm",
                    index === active ? "bg-accent" : "hover:bg-muted",
                  )}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => pick(option.value)}
                >
                  <span>{highlight(option.label, needle)}</span>
                  {chosen ? <Check className="size-4 shrink-0" /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function highlight(label: string, needle: string) {
  const start = label.toLowerCase().indexOf(needle);
  if (start < 0) {
    return label;
  }
  const end = start + needle.length;
  return (
    <>
      {label.slice(0, start)}
      <span className="font-semibold">{label.slice(start, end)}</span>
      {label.slice(end)}
    </>
  );
}
