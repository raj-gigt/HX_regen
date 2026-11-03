import math

def run_simple_regenerator():
    print("==================================================")
    print("   SIMPLIFIED FIXED-BED REGENERATOR SELECTOR     ")
    print("==================================================")
    
    # 1. Simple Fluid Selection
    print("\nSelect Fluid:")
    print("  [1] Air (Gas)")
    print("  [2] Water (Liquid)")
    fluid_choice = input("Enter choice (1 or 2, default 1): ") or "1"
    
    if fluid_choice == "2":
        # Water properties
        rho_f, Cp_f, mu_f, k_f, Pr_f = 998.0, 4184.0, 1.0e-3, 0.6, 7.0
        fluid_name = "Water"
    else:
        # Air properties
        rho_f, Cp_f, mu_f, k_f, Pr_f = 1.1, 1005.0, 1.9e-5, 0.03, 0.7
        fluid_name = "Air"

    # 2. Simple Material Selection
    print("\nSelect Bed Material:")
    print("  [1] Cordierite (Ceramic - Max 1000°C)")
    print("  [2] Stainless Steel (Metal - Max 600°C)")
    mat_choice = input("Enter choice (1 or 2, default 1): ") or "1"
    
    if mat_choice == "2":
        rho_s, Cp_s, T_max, mat_name = 7800.0, 500.0, 600.0, "Stainless Steel"
    else:
        rho_s, Cp_s, T_max, mat_name = 2400.0, 1000.0, 1000.0, "Cordierite"

    # 3. Simple Matrix Selection
    print("\nSelect Matrix Geometry:")
    print("  [1] Honeycomb Monolith (Low Pressure Drop)")
    print("  [2] Packed Spheres (Standard Bed)")
    matrix_choice = input("Enter choice (1 or 2, default 1): ") or "1"
    
    matrix_type = "honeycomb" if matrix_choice == "1" else "spheres"

    # Basic Operating Inputs
    m_dot = float(input("\nEnter mass flow rate [kg/s] (default 0.5): ") or 0.5)
    T_hot_in = float(input("Enter hot fluid inlet temp [°C] (default 700.0): ") or 700.0)
    
    # Temperature Safety Check
    if T_hot_in > T_max:
        print(f"\n[WARNING] Inlet temp {T_hot_in}°C exceeds {mat_name} limit ({T_max}°C)!")
        return

    # Fixed Search Space Bounds for Quick Testing
    D_range = [0.4, 0.5, 0.6]
    L_range = [0.8, 1.0, 1.2]
    t_cycle = 60.0
    eta_target = 0.70
    delta_P_max = 5000.0

    valid_designs = []

    # Optimization Loop
    for D in D_range:
        for L in L_range:
            Ac = (math.pi / 4.0) * (D ** 2)
            Vb = Ac * L
            
            if matrix_type == "spheres":
                eps, dp, a = 0.40, 0.01, 360.0
                G = m_dot / Ac
                Rep = (G * dp) / (mu_f * (1.0 - eps))
                if Rep < 200 or Rep > 15000: continue
                f = (1.75 / (eps ** 3)) + (150.0 * (1.0 - eps)) / (Rep * (eps ** 3))
                delta_P = f * (L / dp) * ((G ** 2) / (2.0 * rho_f)) * ((1.0 - eps) / (eps ** 3))
                j_H = 2.06 * (Rep ** -0.575)
                h = (j_H * G * Cp_f) / (Pr_f ** (2.0 / 3.0))
            else:
                eps, Dh, a = 0.70, 0.002, 1400.0
                G = m_dot / (Ac * eps)
                Re_chan = (G * Dh) / mu_f
                f = 16.0 / Re_chan if Re_chan > 0 else 0
                delta_P = 4.0 * f * (L / Dh) * ((G ** 2) / (2.0 * rho_f))
                Nu = 3.66
                h = (Nu * k_f) / Dh

            Aht = a * Vb
            Lambda = (h * Aht) / (m_dot * Cp_f)
            Ms = Vb * (1.0 - eps) * rho_s
            Pi = (h * Aht / (Ms * Cp_s)) * t_cycle
            
            eta = (Lambda / (Lambda + 2.0 + (Pi / 2.0))) * (1.0 - (Pi ** 2) / (12.0 * ((Lambda + 2.0) ** 2)))
            eta = max(0.0, min(1.0, eta))
            
            if eta >= eta_target and delta_P <= delta_P_max:
                valid_designs.append({
                    "D": D, "L": L, "eta": eta, "dP": delta_P, "Ms": Ms,
                    "score": delta_P + (1.0 - eta) * 10000
                })

    print("\n==================================================")
    if not valid_designs:
        print("RESULT: No design met constraints. Try relaxing targets.")
    else:
        opt = min(valid_designs, key=lambda x: x["score"])
        print("RESULT: OPTIMUM DESIGN FOUND!")
        print("==================================================")
        print(f"Fluid: {fluid_name} | Material: {mat_name} | Matrix: {matrix_type.capitalize()}")
        print(f"Optimal Diameter (D): {opt['D']} m")
        print(f"Optimal Length (L):   {opt['L']} m")
        print(f"Thermal Effectiveness: {opt['eta']*100:.1f}%")
        print(f"Total Pressure Drop:   {opt['dP']:.1f} Pa")
        print(f"Solid Matrix Mass:     {opt['Ms']:.1f} kg")
    print("==================================================")

if __name__ == "__main__":
    run_simple_regenerator()