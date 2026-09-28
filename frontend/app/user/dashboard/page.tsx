"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import axios from "axios";
import GrievanceChatbot from "@/components/GrievanceChatbot";
import GrievanceList from "@/components/GrievanceList";

interface Grievance {
  id: number;
  description: string;
  status: string;
  category?: string;
  priority?: string;
  region?: string;
  solution?: string;
  assigned_officer_name?: string;
  created_at?: string;
}

export default function UserDashboard() {
  const [grievances, setGrievances] = useState<Grievance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const router = useRouter();

  const fetchGrievances = useCallback(async () => {
    try {
      // 1. Check if token exists before making request
      const token = localStorage.getItem("token");
      if (!token) {
        throw new Error("No access token found. Please login.");
      }

      const res = await api.get("/grievance/my-grievances");
      setGrievances(res.data);
    } catch (err: unknown) {
      console.error("Dashboard Error:", err);

      // 2. Handle 401 Unauthorized (Token expired/invalid)
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 401) {
          setError("Session expired. Redirecting to login...");
          setTimeout(() => {
            localStorage.removeItem("token");
            router.push("/auth/login/user");
          }, 2000);
        } else if (err.message === "Network Error") {
          setError("Cannot connect to server. Is the backend running?");
        } else {
          const detail = (err.response?.data as { detail?: string })?.detail;
          setError(detail || "Failed to load grievances.");
        }
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to load grievances.");
      }
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    fetchGrievances();
  }, [fetchGrievances]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    router.push("/");
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-100 to-gray-200">
      <nav className="bg-white shadow-md fixed top-0 left-0 w-full z-50 px-8 py-4 flex justify-between items-center">
        <h1 className="text-2xl font-semibold text-blue-700">User Dashboard</h1>
        <button
          onClick={handleLogout}
          className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg font-medium transition"
        >
          Logout
        </button>
      </nav>

      <div className="pt-24 px-6 md:px-12 pb-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
          
          {/* Chatbot */}
          <div className="w-full">
            <GrievanceChatbot
              onSubmitted={(newItem) => setGrievances((prev) => [newItem as unknown as Grievance, ...prev])}
            />
          </div>

          {/* Grievance List */}
          <div className="bg-white rounded-2xl p-6 shadow-lg border min-h-[400px]">
            <h2 className="text-2xl font-bold mb-4 text-gray-800">Your Grievances</h2>

            {loading ? (
              <div className="flex justify-center items-center h-40">
                 <p className="text-gray-500 animate-pulse">Loading data...</p>
              </div>
            ) : error ? (
              <div className="bg-red-50 text-red-600 p-4 rounded-lg border border-red-200">
                ⚠️ {error}
              </div>
            ) : grievances.length === 0 ? (
              <div className="text-center py-10 text-gray-500">
                <p className="text-lg font-medium">No grievances yet.</p>
                <p className="text-sm">Use the AI Assistant to file one!</p>
              </div>
            ) : (
              <GrievanceList grievances={grievances} onGrievanceUpdated={fetchGrievances} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}