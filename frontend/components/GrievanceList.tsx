"use client";

import { useState } from "react";
import {
  MapPin,
  AlertTriangle,
  Calendar,
  CheckCircle,
  Clock,
  AlertCircle,
  History,
  XCircle,
  X,
  User,
  Bot,
  Shield,
  ArrowRight
} from "lucide-react";
import axios from "axios";
import api from "@/lib/api";

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

interface AuditEvent {
  id: number;
  grievance_id: number;
  actor_id?: number | null;
  actor_name?: string | null;
  actor_role: string;
  event_type: string;
  old_value?: string | null;
  new_value?: string | null;
  timestamp: string;
  metadata_json?: string | null;
}

interface GrievanceListProps {
  grievances: Grievance[];
  onGrievanceUpdated?: () => void;
}

export default function GrievanceList({ grievances, onGrievanceUpdated }: GrievanceListProps) {
  const [selectedGrievanceId, setSelectedGrievanceId] = useState<number | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [withdrawingId, setWithdrawingId] = useState<number | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // Status Badge Colors
  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case "resolved":
        return "bg-green-100 text-green-700 border-green-200";
      case "in progress":
        return "bg-blue-100 text-blue-700 border-blue-200";
      case "withdrawn":
        return "bg-gray-100 text-gray-500 border-gray-300 line-through";
      case "pending":
        return "bg-yellow-100 text-yellow-700 border-yellow-200";
      default:
        return "bg-gray-100 text-gray-700 border-gray-200";
    }
  };

  // Status Icons
  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case "resolved": return <CheckCircle size={14} />;
      case "pending": return <Clock size={14} />;
      case "withdrawn": return <XCircle size={14} />;
      default: return <AlertCircle size={14} />;
    }
  };

  // Fetch immutable audit trail for a grievance
  const handleOpenAuditTrail = async (grievanceId: number) => {
    setSelectedGrievanceId(grievanceId);
    setLoadingAudit(true);
    setAuditError("");
    setAuditEvents([]);

    try {
      const res = await api.get(`/grievance/${grievanceId}/audit-trail`);
      setAuditEvents(res.data.events || []);
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setAuditError(err.response?.data?.detail || "Failed to load audit trail.");
      } else {
        setAuditError("Failed to load audit trail.");
      }
    } finally {
      setLoadingAudit(false);
    }
  };

  // Handle grievance withdrawal by citizen
  const handleWithdrawGrievance = async (grievanceId: number) => {
    setActionLoading(true);
    try {
      await api.post(`/grievance/${grievanceId}/withdraw`, {
        reason: withdrawReason || "Withdrawn by citizen"
      });
      setWithdrawingId(null);
      setWithdrawReason("");
      if (onGrievanceUpdated) {
        onGrievanceUpdated();
      }
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        alert(err.response?.data?.detail || "Failed to withdraw grievance.");
      } else {
        alert("Failed to withdraw grievance.");
      }
    } finally {
      setActionLoading(false);
    }
  };

  const getActorIcon = (role: string) => {
    switch (role.toLowerCase()) {
      case "citizen":
      case "user":
        return <User size={14} className="text-blue-500" />;
      case "officer":
        return <Shield size={14} className="text-purple-500" />;
      case "admin":
        return <Shield size={14} className="text-red-500" />;
      case "ai_worker":
      case "ai":
        return <Bot size={14} className="text-emerald-500" />;
      default:
        return <AlertCircle size={14} className="text-amber-500" />;
    }
  };

  return (
    <>
      <ul className="space-y-4">
        {grievances.map((g) => {
          const isTerminal = ["resolved", "closed", "withdrawn"].includes(g.status.toLowerCase());

          return (
            <li
              key={g.id}
              className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow"
            >
              {/* Top Row: Category Badge + Status Badge */}
              <div className="flex justify-between items-start mb-3">
                <span className="px-3 py-1 text-xs font-semibold bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded-full uppercase tracking-wider">
                  {g.category || "General"}
                </span>

                <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border text-xs font-medium ${getStatusColor(g.status)}`}>
                  {getStatusIcon(g.status)}
                  <span>{g.status}</span>
                </div>
              </div>

              {/* Description */}
              <p className="text-gray-800 dark:text-gray-200 font-medium leading-relaxed mb-4">
                {g.description}
              </p>

              {/* Solution/Resolution if available */}
              {g.solution && (
                <div className="mb-4 p-3 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-lg text-xs text-emerald-800 dark:text-emerald-200">
                  <div className="font-semibold flex items-center gap-1.5 mb-1">
                    <CheckCircle size={14} className="text-emerald-600" />
                    <span>Resolution Summary</span>
                  </div>
                  <p>{g.solution}</p>
                </div>
              )}

              {/* Metadata Row: Priority, Region, Date, and Actions */}
              <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-700 pt-3">
                <div className="flex flex-wrap items-center gap-4">
                  {/* Priority */}
                  <div className={`flex items-center gap-1.5 ${
                    g.priority === "High" || g.priority === "Critical" || g.priority === "HIGH" || g.priority === "CRITICAL"
                      ? "text-red-500 font-semibold"
                      : ""
                  }`}>
                    <AlertTriangle size={14} />
                    <span>{g.priority || "Normal"} Priority</span>
                  </div>

                  {/* Region */}
                  {g.region && (
                    <div className="flex items-center gap-1.5">
                      <MapPin size={14} />
                      <span>{g.region}</span>
                    </div>
                  )}

                  {/* Date */}
                  {g.created_at && (
                    <div className="flex items-center gap-1.5">
                      <Calendar size={14} />
                      <span>{new Date(g.created_at).toLocaleDateString()}</span>
                    </div>
                  )}
                </div>

                {/* Feature 4 Action Buttons: Audit Trail & Withdraw */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleOpenAuditTrail(g.id)}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/30 rounded-lg transition"
                    title="View complete immutable history"
                  >
                    <History size={13} />
                    <span>Audit Trail</span>
                  </button>

                  {!isTerminal && (
                    <button
                      onClick={() => setWithdrawingId(g.id)}
                      className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 dark:bg-red-900/30 rounded-lg transition"
                      title="Withdraw this grievance"
                    >
                      <XCircle size={13} />
                      <span>Withdraw</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Withdraw Confirmation Inline Box */}
              {withdrawingId === g.id && (
                <div className="mt-4 p-4 border border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20 rounded-xl space-y-3">
                  <p className="text-xs font-medium text-red-800 dark:text-red-300">
                    Are you sure you want to withdraw this grievance? This action cannot be undone.
                  </p>
                  <input
                    type="text"
                    placeholder="Reason for withdrawal (optional)"
                    value={withdrawReason}
                    onChange={(e) => setWithdrawReason(e.target.value)}
                    className="w-full text-xs px-3 py-2 border rounded-lg focus:outline-none focus:ring-1 focus:ring-red-400 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => {
                        setWithdrawingId(null);
                        setWithdrawReason("");
                      }}
                      className="px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200 rounded-lg"
                      disabled={actionLoading}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => handleWithdrawGrievance(g.id)}
                      className="px-3 py-1 text-xs font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                      disabled={actionLoading}
                    >
                      {actionLoading ? "Withdrawing..." : "Confirm Withdrawal"}
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {/* Feature 4: Immutable Audit Trail Modal */}
      {selectedGrievanceId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-2xl max-w-lg w-full max-h-[85vh] flex flex-col shadow-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
            {/* Header */}
            <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <History size={18} className="text-blue-600" />
                  <span>Immutable Audit Trail</span>
                </h3>
                <p className="text-xs text-gray-500">
                  Complaint #{selectedGrievanceId} chronological event ledger
                </p>
              </div>
              <button
                onClick={() => setSelectedGrievanceId(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1 rounded-lg"
              >
                <X size={18} />
              </button>
            </div>

            {/* Content / Timeline */}
            <div className="p-6 overflow-y-auto space-y-4 flex-1">
              {loadingAudit ? (
                <div className="text-center py-8 text-sm text-gray-500 animate-pulse">
                  Loading verified audit events...
                </div>
              ) : auditError ? (
                <div className="p-4 bg-red-50 text-red-600 text-xs rounded-lg border border-red-200">
                  {auditError}
                </div>
              ) : auditEvents.length === 0 ? (
                <div className="text-center py-8 text-sm text-gray-500">
                  No audit events recorded yet.
                </div>
              ) : (
                <ol className="relative border-l border-blue-200 dark:border-blue-900 ml-3 space-y-6">
                  {auditEvents.map((ev) => (
                    <li key={ev.id} className="ml-6">
                      <span className="absolute -left-3 flex items-center justify-center w-6 h-6 bg-blue-100 dark:bg-blue-950 rounded-full border-2 border-white dark:border-gray-900 shadow">
                        {getActorIcon(ev.actor_role)}
                      </span>

                      <div className="bg-gray-50 dark:bg-gray-800/60 p-3.5 rounded-xl border border-gray-100 dark:border-gray-700/60">
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs font-bold uppercase tracking-wider text-blue-700 dark:text-blue-400">
                            {ev.event_type.replace(/_/g, " ")}
                          </span>
                          <span className="text-[10px] text-gray-400">
                            {new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {new Date(ev.timestamp).toLocaleDateString()}
                          </span>
                        </div>

                        <div className="text-xs text-gray-700 dark:text-gray-300 font-medium mb-1">
                          Actor: <span className="font-semibold text-gray-900 dark:text-white">{ev.actor_name || ev.actor_role}</span>{" "}
                          <span className="text-[10px] text-gray-400 uppercase">({ev.actor_role})</span>
                        </div>

                        {(ev.old_value || ev.new_value) && (
                          <div className="text-xs text-gray-600 dark:text-gray-300 flex items-center gap-1.5 mt-1">
                            {ev.old_value && (
                              <>
                                <span className="line-through text-gray-400">{ev.old_value}</span>
                                <ArrowRight size={12} className="text-gray-400" />
                              </>
                            )}
                            <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                              {ev.new_value}
                            </span>
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-800 flex justify-end">
              <button
                onClick={() => setSelectedGrievanceId(null)}
                className="px-4 py-2 text-xs font-semibold bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 rounded-lg text-gray-700 dark:text-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}