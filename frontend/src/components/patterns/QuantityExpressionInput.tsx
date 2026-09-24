import { useEffect, useState } from "react";
import { useI18n } from "../../lib/i18n";
import { evaluateQuantity, isSum } from "../../lib/quantityExpression";
import { formatQuantity } from "../../lib/units";
import { Input } from "../ui/input";

/**
 * A quantity box that also takes a sum: `15.67+15.27+15.9-2.8` is the weights of the
 * rolls used less what is left on the last one, and the box shows what it comes to.
 *
 * The form only ever holds the resulting number -- the backend stores a quantity, not
 * a formula. A text that is not a number or a sum leaves NaN in the form, which its
 * schema refuses, so a half-typed `15.67+` can never be saved as the figure before it.
 */
export function QuantityExpressionInput({
  id,
  value,
  onValueChange,
  unit,
}: {
  id: string;
  value: number;
  onValueChange: (value: number) => void;
  /** Shown beside the result of a sum, when the item's unit is known. */
  unit?: string | null;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(() => (Number.isFinite(value) ? String(value) : ""));

  // The form can change the value under the box -- a draft loading in, a reset. Follow
  // it unless the box already says that number, so a sum being typed is not overwritten
  // by its own partial result.
  useEffect(() => {
    if (!Number.isFinite(value)) return;
    if (evaluateQuantity(text) !== value && !(text.trim() === "" && value === 0)) setText(String(value));
    // Only when the form's value moves, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const result = evaluateQuantity(text);
  const invalid = text.trim() !== "" && result === null;

  return (
    <div className="space-y-1">
      <Input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={text}
        aria-invalid={invalid}
        onChange={(event) => {
          setText(event.target.value);
          // An emptied box is 0, as it is in the number boxes around it.
          const next = event.target.value.trim() === "" ? 0 : evaluateQuantity(event.target.value);
          onValueChange(next ?? Number.NaN);
        }}
      />
      {invalid ? (
        <p className="text-xs text-destructive">{t("common.quantitySum.invalid")}</p>
      ) : (
        isSum(text) &&
        result !== null && <p className="text-xs text-muted-foreground">= {formatQuantity(result, unit)}</p>
      )}
    </div>
  );
}
