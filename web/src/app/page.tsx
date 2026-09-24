import { ApiStatus } from "@/components/ApiStatus";
import { SplitApp } from "@/components/split/SplitApp";

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col">
      <header className="px-4 pt-6">
        <h1 className="text-2xl font-semibold">ReceiptSplit</h1>
      </header>
      <main className="flex-1 px-4 pt-4">
        <SplitApp />
      </main>
      <footer className="px-4 py-3 text-sm opacity-70">
        <ApiStatus />
      </footer>
    </div>
  );
}
