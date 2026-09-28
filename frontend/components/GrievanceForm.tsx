"use client";

import { useState } from "react";
import api from "@/lib/api";
import { AxiosError } from "axios";

interface GrievanceFormProps {
  onSubmitted?: (grievance: Record<string, unknown>) => void;
}

export default function GrievanceForm({ onSubmitted }: GrievanceFormProps) {
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage("");

    try {
      const res = await api.post("/grievance/submit", { description });
      setMessage("Grievance submitted successfully!");
      if (onSubmitted) onSubmitted(res.data); // <-- safely call it
      setDescription("");
    } catch (err) {
      const error = err as AxiosError;
      console.error(error);
      setMessage("Error submitting grievance. Try again later.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white p-6 rounded-lg shadow">
      <h2 className="text-xl font-semibold mb-4">Submit a New Grievance</h2>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe your issue..."
          className="border p-3 rounded-lg"
          required
        />

        <button
          type="submit"
          className="bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition"
          disabled={loading}
        >
          {loading ? "Submitting..." : "Submit Grievance"}
        </button>
      </form>
      {message && <p className="mt-3 text-sm text-green-600">{message}</p>}
    </div>
  );
}
