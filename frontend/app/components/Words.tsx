import { Fragment, type CSSProperties } from "react";

// Splits a heading into word spans so CSS can blur them in one at a time (after React Bits'
// BlurText). Screen readers still read the plain sentence.
export default function Words({ text, className = "w" }: { text: string; className?: string }) {
  return text.split(" ").map((word, i) => (
    <Fragment key={i}>
      <span className={className} style={{ "--i": i } as CSSProperties}>
        {word}
      </span>{" "}
    </Fragment>
  ));
}
