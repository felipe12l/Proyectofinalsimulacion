# Project Specification: Naval Defense Simulation System

## 1. Executive Summary
This project implements a discrete-event and continuous-time hybrid simulation of an anti-missile defense system on a drifting naval vessel. The model evaluates system throughput, threat tracking, queue dynamics, and defense efficiency under deterministic and stochastic environmental conditions.

The system is designed for **serverless execution** (pure Python, stateless runtime, zero external heavy dependencies such as NumPy or Pandas for fast cold-starts).

---

## 2. Environment & Simulation Parameters

### 2.1 Environmental Variables
- **Gravity ($g$):** $9.81 \text{ m/s}^2$ (Deterministic, Constant)
- **Air Density ($\rho$):** $1.0 - 1.225 \text{ kg/m}^3$ (Deterministic, Constant or $\rho(h)$)
- **Wind Speed ($v_w$):** $0 - 20 \text{ m/s}$ (Stochastic, updated via $v_w + \eta$ where $\eta \sim \mathcal{N}(0, \sigma^2)$)
- **Wind Direction ($\theta_w$):** $[0, 2\pi) \text{ rad}$ (Stochastic, uniform per run)
- **Wave Height ($H_s$):** $0 - 4 \text{ m}$ (Stochastic, random amplitude per run)
- **Ship Pitch ($\varphi$):** $\pm 0.1 \text{ rad}$ ($A \sin(\omega t + \psi)$)
- **Radar Clutter Intensity ($\lambda_c$):** $0 - 5 \text{ echoes/sweep}$ (Stochastic, Poisson distribution per sweep)
- **Radar Horizon ($d_h$):** Calculated in km as $d_h = 3.57(\sqrt{h_a} + \sqrt{h_o})$, where $h_a$ is radar height and $h_o$ is threat/target altitude.
- **Random Seed ($S$):** Integer, fixed per run for exact reproducibility.
- **Simulation Mode ($m$):** `"det"` (Deterministic) | `"est"` (Stochastic).
- **Integration Step ($\Delta t$):** $0.001 - 0.05 \text{ s}$ (Fixed continuous integration step).

---

## 3. Entities & Variables

### 3.1 Attack Variables (Threat / Missile)
- **Position ($r_a$):** Vector in $\mathbb{R}^3$ ($[x, y, z]$ in meters).
- **Velocity ($v_a$):** $200 - 1000 \text{ m/s}$. Updated via $v + a \Delta t$.
- **Drag Coefficient ($C_d$):** $0.2 - 0.6$ (Constant per threat).
- **Mass ($m_a$):** $100 - 700 \text{ kg}$.
- **Frontal Area ($A_a$):** $0.05 - 0.3 \text{ m}^2$.
- **Attack Profile ($P$):** Ballistic (high altitude profile) or Sea-Skimming / Rasante (low altitude profile).
- **Threat Count ($N_a$):** $5, 10, 20$ (Saturation parameter).
- **Salvo Launch Interval ($\Delta t_a$):** $0.5 - 5 \text{ s}$.
- **Threat State ($E_a$):** Finite State Machine state ($S_0$ through $S_6$).
- **Lethality ($L_a$):** Inocuous or Lethal based on projected impact point within ship's protection radius.

### 3.2 Defense Variables (Combat System & Interceptors)
- **Radar Range ($R_r$):** $20 - 60 \text{ km}$.
- **Sweep Period ($T_b$):** $0.5 - 4 \text{ s}$ (Pulse interval for target acquisition).
- **Tracking Capacity ($C_r$):** $8 - 32 \text{ tracks}$ (Maximum simultaneous active tracks).
- **Detection Probability ($P_d$):** $0.7 - 1.0$ (Decreases with distance and clutter intensity).
- **Time To Impact (TTI):** Calculated dynamically as $d / v_{\text{closing}}$.
- **TTI Threshold ($\tau_{\text{TTI}}$):** $3 - 15 \text{ s}$ (Prioritizes targets with lowest TTI).
- **Fire Control Latency ($t_{cf}$):** $0.5 - 3 \text{ s}$ (System delay before interceptor launch).
- **Available Interceptors ($N_i$):** $8 - 40 \text{ units}$. Decremented upon allocation.
- **Interceptor Velocity ($v_i$):** $600 - 1200 \text{ m/s}$ (Proportional navigation vector towards threat).
- **Fuze Radius ($r_e$):** $5 - 20 \text{ m}$ (Proximity detonation threshold).
- **Kill Probability ($P_k$):** $0.6 - 0.95$ (Evaluated upon proximity detonation).

---

## 4. Finite State Machine (FSM)

Each threat entity transitions through 7 discrete states:

```
                  [Start]
                     │
                     ▼
             ┌──────────────┐
             │      S0      │◄── (Sweep Failure)
             │ Not Detected │
             └──────┬───────┘
                    │ Detection (Pd check & Radar Horizon)
                    ▼
             ┌──────────────┐
             │      S1      │───────► Track Lost ──► S0
             │   Tracked    │
             └──────┬───────┘
                    │ Evaluation Complete (Project Impact)
                    ▼
             ┌──────────────┐ ─── (Inocuous) ────► ┌───────────┐
             │      S2      │                     │    S6     │
             │  Evaluated   │                     │ Inocuous  │
             └──────┬───────┘                     └───────────┘
                    │ Allocation (Lethal, Ni > 0, TTI check)
                    ▼
             ┌──────────────┐
             │      S3      │ ─── (Intercept Failure) ───► S2 (Re-evaluate)
             │   Engaged    │
             └──────┬───────┘
                    │ Detonation & Pk Hit
                    ▼
             ┌──────────────┐                     ┌───────────┐
             │      S4      │                     │    S5     │
             │ Neutralized  │                     │  Impact   │
             └──────────────┘                     └───────────┘
                    ▲                                   ▲
                    │                                   │
                    └─────── (Altitude <= 0) ───────────┘
```

### State Definitions
| State | Name | Description |
| :--- | :--- | :--- |
| **$S_0$** | No Detectada | Threat is in flight but undetected by radar. |
| **$S_1$** | Rastreada | Target acquired; active tracking slot allocated. |
| **$S_2$** | Evaluated | Trajectory extrapolated; classified as lethal or innocuous. |
| **$S_3$** | Enganchada | Interceptor launched and guided towards threat. |
| **$S_4$** | Neutralizada | Interceptor detonated within $r_e$ and $P_k$ succeeded. (Terminal) |
| **$S_5$** | Impacto | Threat reached altitude $\le 0$ within ship protection zone. (Terminal) |
| **$S_6$** | Inocua | Threat trajectory falls harmlessly into the sea. (Terminal) |

### Transition Rules
1. **$S_0 \to S_1$ (Detection):** Occurs during radar sweep if distance $d \le \min(R_r, d_h)$, radar tracks available ($< C_r$), and $P_d$ check passes.
2. **$S_0 \to S_0$ (Failed Sweep):** $P_d$ check fails or capacity exceeded; retried next sweep.
3. **$S_1 \to S_2$ (Evaluation):** Extrapolates trajectory to estimate ground/sea impact coordinates.
4. **$S_2 \to S_6$ (Innocuous):** Impact point is outside ship's protection radius.
5. **$S_2 \to S_3$ (Engagement):** Classified lethal, interceptors remaining ($N_i > 0$), and $\text{TTI} \ge t_{cf} + t_{\text{flight}}$.
6. **$S_2 \to S_2$ (Queue/Wait):** Lethal target, but $N_i = 0$ or pending fire control slot.
7. **$S_3 \to S_4$ (Neutralization):** Interceptor distance to threat $\le r_e$ and $P_k$ check passes.
8. **$S_3 \to S_2$ (Miss / Re-engage):** Interceptor detonates or passes without destroying threat; re-evaluated.
9. **$S_1, S_2, S_3 \to S_5$ (Impact):** Threat altitude $z \le 0$ within ship hit radius.

---

## 5. Mathematical & Simulation Models

### 5.1 System Dynamics (Discrete-Time Integration)
State updates follow:
$$x_{k+1} = f(x_k, u_k, w_k)$$
where $x_k$ is the state vector (positions, velocities), $u_k$ is control input (interceptor guidance), and $w_k$ represents stochastic disturbances (wind, noise).

Drag Acceleration Calculation:
$$F_{\text{drag}} = -\frac{1}{2} \rho C_d A_a \|v_{\text{rel}}\| v_{\text{rel}}$$
$$a = \frac{F_{\text{drag}}}{m_a} + [0, 0, -g]^T$$

### 5.2 Discrete Event Queue Model
Intercept slots follow capacity-constrained processing:
$$Q_{k+1} = \max(0, Q_k + A_k - D_k)$$
$$D_k = \min(Q_k + A_k, C_k)$$
where $Q_k$ is pending queue length, $A_k$ is new threat arrivals, $D_k$ is processed detections, and $C_k$ is system track capacity.

### 5.3 Performance Indicators
- **System Throughput ($X$):**
  $$X = \frac{N_{\text{processed}}}{T_{\text{simulation}}}$$
- **Average Wait Time ($\bar{W}$):**
  $$\bar{W} = \frac{1}{N} \sum_{i=1}^{N} W_i$$
  where $W_i$ is the delay between detection evaluation ($S_1 \to S_2$) and interceptor engagement ($S_3$).

---

## 6. Serverless Architecture Requirements

- **Language:** Standard Python 3.10+
- **External Dependencies:** **NONE** (Use `math`, `random`, `dataclasses`, `enum`, `json`, `statistics`).
- **Entrypoint:** Stateless `lambda_handler(event, context)` or `run_simulation(payload: dict)`.
- **Determinism:** Passing a specific `seed` must produce identical numerical outputs across AWS Lambda, Cloud Functions, or local execution.