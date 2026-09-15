import { ApiStatus } from "@/components/ApiStatus";

export default function Home() {
  return (
    <main className="p-6">
      <h1 className="text-2xl font-semibold">receipt-splitter</h1>
      <ApiStatus />
    </main>
  );
}
