import tkinter as tk
from tkinter import ttk

class Calculator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ALTRON Calculator")
        self.geometry("320x420")
        self.resizable(False, False)
        self.configure(bg="#2b2b2b")
        self.expression = ""
        self.input_text = tk.StringVar()
        self._create_widgets()
        self._bind_keys()

    def _create_widgets(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton',
                        font=('Segoe UI', 14),
                        padding=10,
                        background='#4c4c4c',
                        foreground='white')
        style.map('TButton',
                  background=[('active', '#6c6c6c')])

        # Entry display
        entry_frame = ttk.Frame(self)
        entry_frame.pack(fill='x', padx=10, pady=20)
        entry = ttk.Entry(entry_frame,
                          textvariable=self.input_text,
                          font=('Segoe UI', 24),
                          justify='right',
                          state='readonly')
        entry.pack(fill='x', ipady=10)

        # Buttons frame
        btn_frame = ttk.Frame(self)
        btn_frame.pack(expand=True, fill='both', padx=10, pady=5)

        buttons = [
            ('C', 0, 0), ('⌫', 0, 1), ('%', 0, 2), ('/', 0, 3),
            ('7', 1, 0), ('8', 1, 1), ('9', 1, 2), ('*', 1, 3),
            ('4', 2, 0), ('5', 2, 1), ('6', 2, 2), ('-', 2, 3),
            ('1', 3, 0), ('2', 3, 1), ('3', 3, 2), ('+', 3, 3),
            ('0', 4, 0, 2), ('.', 4, 2), ('=', 4, 3),
        ]

        for btn in buttons:
            text, r, c = btn[0], btn[1], btn[2]
            colspan = btn[3] if len(btn) == 4 else 1
            b = ttk.Button(btn_frame, text=text,
                           command=lambda t=text: self.on_button_click(t))
            b.grid(row=r, column=c, columnspan=colspan,
                   sticky='nsew', padx=5, pady=5)

        for i in range(5):
            btn_frame.rowconfigure(i, weight=1)
        for i in range(4):
            btn_frame.columnconfigure(i, weight=1)

    def on_button_click(self, char):
        if char == 'C':
            self.expression = ""
            self.input_text.set("")
        elif char == '⌫':
            self.expression = self.expression[:-1]
            self.input_text.set(self.expression)
        elif char == '=':
            try:
                result = str(eval(self.expression))
                self.input_text.set(result)
                self.expression = result
            except Exception:
                self.input_text.set("Error")
                self.expression = ""
        else:
            self.expression += str(char)
            self.input_text.set(self.expression)

    def _bind_keys(self):
        self.bind('<Return>', lambda e: self.on_button_click('='))
        self.bind('<BackSpace>', lambda e: self.on_button_click('⌫'))
        for key in '0123456789+-*/.%':
            self.bind(key, lambda e, k=key: self.on_button_click(k))

if __name__ == "__main__":
    app = Calculator()
    app.mainloop()
