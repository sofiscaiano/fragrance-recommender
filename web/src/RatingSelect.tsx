import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

const SCORES = [
  { value: "1", label: "Odio" },
  { value: "2", label: "Disgusto" },
  { value: "3", label: "Ok" },
  { value: "4", label: "Me gusta" },
  { value: "5", label: "Me encanta" },
] as const;

type RatingSelectProps = {
  value: string | null;
  onChange: (value: string | null) => void;
};

export function RatingSelect({ value, onChange }: RatingSelectProps) {
  return (
    <Label className="font-normal text-muted-foreground">
      Mi puntuación
      <Select
        value={value}
        onValueChange={(next) => onChange(next)}
        items={SCORES.map((score) => ({ value: score.value, label: score.label }))}
      >
        <SelectTrigger className="w-36" aria-label="Mi puntuación">
          <SelectValue placeholder="—" />
        </SelectTrigger>
        <SelectContent align="end">
          {SCORES.map((score) => (
            <SelectItem key={score.value} value={score.value}>
              {score.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </Label>
  );
}
