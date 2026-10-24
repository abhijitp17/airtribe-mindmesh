"use client";

import { useState, type FormEvent } from "react";
import type { ActivityType, PlanItemCreate } from "@/lib/api-goals";
import { activityLabel } from "./ActivityBadge";
import { fieldStyle } from "./styles";

const ACTIVITIES: ActivityType[] = ["learn", "practice", "review", "drill", "mock_interview"];

function isActivity(v: string): v is ActivityType {
  return (ACTIVITIES as string[]).includes(v);
}

type Props = {
  minDate: string;
  deadline: string;
  defaultMinutes: number;
  busy: boolean;
  onAdd: (body: PlanItemCreate) => Promise<boolean>;
  onCancel: () => void;
};

export default function AddSessionForm({ minDate, deadline, defaultMinutes, busy, onAdd, onCancel }: Props) {
  const [topic, setTopic] = useState("");
  const [activity, setActivity] = useState<ActivityType>("learn");
  const [date, setDate] = useState(minDate);
  const [minutes, setMinutes] = useState(Math.min(30, defaultMinutes));

  const valid = topic.trim().length > 0 && date >= minDate && date <= deadline && minutes >= 5 && minutes <= 480;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid) return;
    const ok = await onAdd({ topic: topic.trim(), activity_type: activity, scheduled_date: date, estimated_minutes: minutes });
    if (ok) setTopic("");
  }

  return (
    <form className="glass card stack" onSubmit={submit} aria-labelledby="add-h">
      <h3 id="add-h">Add a session</h3>
      <div>
        <label htmlFor="add-topic">Topic</label>
        <input id="add-topic" type="text" maxLength={255} value={topic} onChange={(e) => setTopic(e.target.value)} required />
      </div>
      <div className="grid2">
        <div>
          <label htmlFor="add-act">Activity</label>
          <select id="add-act" value={activity} onChange={(e) => { if (isActivity(e.target.value)) setActivity(e.target.value); }}>
            {ACTIVITIES.map((a) => <option key={a} value={a}>{activityLabel(a)}</option>)}
          </select>
        </div>
        <div className="grid2">
          <div>
            <label htmlFor="add-date">Date</label>
            <input id="add-date" type="date" min={minDate} max={deadline} value={date} onChange={(e) => setDate(e.target.value)} style={fieldStyle} required />
          </div>
          <div>
            <label htmlFor="add-min">Minutes</label>
            <input id="add-min" type="number" min={5} max={480} step={5} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} style={fieldStyle} required />
          </div>
        </div>
      </div>
      {minutes > defaultMinutes && (
        <div className="notice warn small">This is more than your daily budget of {defaultMinutes} minutes.</div>
      )}
      <div className="row">
        <button type="submit" className="dark" disabled={!valid || busy}>Add session</button>
        <button type="button" className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
