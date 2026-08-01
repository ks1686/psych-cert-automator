import { useState, useCallback, useMemo } from "react";
import { XCircle, AlertTriangle, ArrowUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface IneligibleResult {
  name: string;
  status: IneligibleStatus;
  reason: string;
}

export type IneligibleStatus =
  | "Not Found"
  | "Attendance"
  | "Ambiguous"
  | "Excluded";

interface IneligibilityReportProps {
  entries: IneligibleResult[];
}

function statusBadge(status: IneligibleStatus) {
  switch (status) {
    case "Not Found":
      return (
        <Badge className="border-transparent bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100">
          <XCircle className="mr-1 h-3 w-3" />
          Not Found
        </Badge>
      );
    case "Attendance":
      return (
        <Badge className="border-transparent bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100">
          <AlertTriangle className="mr-1 h-3 w-3" />
          Attendance
        </Badge>
      );
    case "Ambiguous":
      return (
        <Badge className="border-transparent bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-100">
          <AlertTriangle className="mr-1 h-3 w-3" />
          Ambiguous
        </Badge>
      );
    case "Excluded":
      return (
        <Badge className="border-transparent bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100">
          <XCircle className="mr-1 h-3 w-3" />
          Excluded
        </Badge>
      );
    default: {
      const _exhaustive: never = status;
      return _exhaustive;
    }
  }
}

export function IneligibilityReport({ entries }: IneligibilityReportProps) {
  const [eligFilter, setEligFilter] = useState<IneligibleStatus | "All">("All");
  const [eligSortKey, setEligSortKey] = useState<
    "name" | "status" | "reason"
  >("name");
  const [eligSortDir, setEligSortDir] = useState<"asc" | "desc">("asc");

  const filteredIneligible = useMemo(() => {
    let list = [...entries];
    if (eligFilter !== "All") {
      list = list.filter((entry) => entry.status === eligFilter);
    }
    list.sort((a, b) => {
      let cmp = 0;
      if (eligSortKey === "name") cmp = a.name.localeCompare(b.name);
      else if (eligSortKey === "status") cmp = a.status.localeCompare(b.status);
      else cmp = a.reason.localeCompare(b.reason);
      return eligSortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [entries, eligFilter, eligSortKey, eligSortDir]);

  const toggleSort = useCallback(
    (key: "name" | "status" | "reason") => {
      if (eligSortKey === key) {
        setEligSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setEligSortKey(key);
        setEligSortDir("asc");
      }
    },
    [eligSortKey],
  );

  const eligCounts = useMemo(() => {
    const counts: Record<IneligibleStatus | "All", number> = {
      All: entries.length,
      "Not Found": 0,
      Attendance: 0,
      Ambiguous: 0,
      Excluded: 0,
    };
    for (const e of entries) {
      counts[e.status] += 1;
    }
    return counts;
  }, [entries]);

  if (filteredIneligible.length === 0) {
    return null;
  }

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">
        Ineligibility Report ({entries.length} total)
      </h3>

      <div className="mb-3 flex flex-wrap items-center gap-1">
        {(["All", "Not Found", "Attendance", "Ambiguous", "Excluded"] as const).map(
          (filter) => (
            <Button
              key={filter}
              variant={eligFilter === filter ? "default" : "outline"}
              size="sm"
              onClick={() => setEligFilter(filter)}
              className="h-7 text-xs"
            >
              {filter}{" "}
              <span className="ml-1 tabular-nums">({eligCounts[filter]})</span>
            </Button>
          ),
        )}
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead
                className="cursor-pointer select-none"
                onClick={() => toggleSort("name")}
              >
                <span className="inline-flex items-center gap-1">
                  Name
                  <ArrowUpDown className="h-3 w-3" />
                </span>
              </TableHead>
              <TableHead
                className="cursor-pointer select-none w-[120px]"
                onClick={() => toggleSort("status")}
              >
                <span className="inline-flex items-center gap-1">
                  Status
                  <ArrowUpDown className="h-3 w-3" />
                </span>
              </TableHead>
              <TableHead
                className="cursor-pointer select-none"
                onClick={() => toggleSort("reason")}
              >
                <span className="inline-flex items-center gap-1">
                  Reason
                  <ArrowUpDown className="h-3 w-3" />
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredIneligible.map((entry) => (
              <TableRow key={`${entry.name}-${entry.status}`}>
                <TableCell className="font-medium">{entry.name}</TableCell>
                <TableCell>{statusBadge(entry.status)}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {entry.reason}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
