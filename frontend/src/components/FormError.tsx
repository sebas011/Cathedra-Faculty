import { useEffect, useRef } from "react";

export default function FormError({ message }: { message: string }) {
  const summary = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message) summary.current?.focus();
  }, [message]);
  if (!message) return null;
  return <div ref={summary} className="notice error" role="alert" tabIndex={-1}>
    <strong>Please correct the following:</strong>
    <ul>{message.split("; ").map((item, index) => <li key={index}>{item}</li>)}</ul>
    <span>Your entries are still here. Correct the details and try again.</span>
  </div>;
}
