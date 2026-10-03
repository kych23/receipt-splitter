import { ApiStatus } from "@/components/ApiStatus";
import { SplitApp } from "@/components/split/SplitApp";

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col px-4">
      <header className="pt-5 pb-4">
        <h1 className="font-mono text-lg font-semibold tracking-tight">
          ReceiptSplit
        </h1>
      </header>
      <main className="flex-1">
        <SplitApp />
      </main>
      <footer className="py-4 text-sm text-ink-muted">
        <ApiStatus />
      </footer>
    </div>
  );
}
