"""Frases de Charlie Munger para el Inicio: una por semana, en orden.

Solo frases con fuente conocida (libro, charla o asamblea). Para sumar una, agregá una línea con (frase, fuente).
La rotación usa la semana del año, así que la frase es la misma de lunes a domingo aunque se recargue la página.
"""
from datetime import date

FRASES = [
    ("El dinero grande no está en comprar y vender, sino en esperar.",
     "Poor Charlie's Almanack"),
    ("A largo plazo, es difícil que una acción rinda mucho más que el negocio que tiene detrás. Si el negocio gana 18% sobre "
     "el capital durante 20 o 30 años, aunque pagues un precio que parece caro, vas a terminar con un resultado excelente.",
     "Charla en USC, 1994"),
    ("Si no estás dispuesto a reaccionar con calma ante una caída del 50% en el precio dos o tres veces por siglo, "
     "no estás hecho para ser accionista.",
     "Entrevista con la BBC, 2009"),
    ("Es notable cuánta ventaja de largo plazo conseguimos tratando de no ser estúpidos de forma consistente, "
     "en vez de tratar de ser muy inteligentes.",
     "Poor Charlie's Almanack"),
    ("Invertí, siempre invertí: pensá el problema al revés. En vez de preguntar cómo tener éxito, preguntá qué te haría "
     "fracasar, y evitalo.",
     "Poor Charlie's Almanack"),
    ("Lo único que quiero saber es dónde me voy a morir, así no voy nunca ahí.",
     "Poor Charlie's Almanack"),
    ("Nunca, nunca pienses en otra cosa cuando deberías estar pensando en el poder de los incentivos.",
     "The Psychology of Human Misjudgment, 1995"),
    ("Para un hombre con un martillo, todo problema parece un clavo. Hay que tener varios modelos en la cabeza.",
     "Charla en USC, 1994"),
    ("Veo constantemente gente que progresa en la vida sin ser la más inteligente, a veces ni siquiera la más trabajadora, "
     "pero que son máquinas de aprender.",
     "Discurso de graduación en USC, 2007"),
    ("La forma más segura de conseguir lo que querés es merecer lo que querés.",
     "Discurso de graduación en USC, 2007"),
    ("Pasá cada día tratando de ser un poco más sabio que cuando te levantaste. Paso a paso se avanza, aunque no "
     "necesariamente con pasos rápidos.",
     "Discurso de graduación en USC, 2007"),
    ("La envidia, el resentimiento, la venganza y la autocompasión son formas de pensar desastrosas.",
     "Discurso de graduación en USC, 2007"),
    ("No vendas nada que no comprarías vos mismo. No trabajes para nadie a quien no respetes y admires. "
     "Trabajá solo con gente que disfrutes.",
     "Discurso de graduación en USC, 2007"),
    ("En toda mi vida no conocí a ninguna persona sabia que no leyera todo el tiempo. Ninguna, cero.",
     "Poor Charlie's Almanack"),
    ("No hace falta ser brillante: alcanza con ser un poco más sensato que los demás, en promedio, durante mucho, mucho tiempo.",
     "Poor Charlie's Almanack"),
    ("Tenemos tres canastas para las inversiones: sí, no, y demasiado difícil de entender.",
     "Poor Charlie's Almanack"),
    ("Hace falta carácter para quedarse sentado con todo ese efectivo sin hacer nada. No llegué adonde estoy yendo detrás de "
     "oportunidades mediocres.",
     "Asamblea de Berkshire Hathaway"),
    ("La envidia es un pecado realmente estúpido, porque es el único con el que nunca te podés divertir.",
     "Asamblea de Berkshire Hathaway"),
    ("Imitar al rebaño invita a volver a la media: a un resultado apenas promedio.",
     "Poor Charlie's Almanack"),
    ("Los dos insistimos en tener mucho tiempo disponible casi todos los días para simplemente sentarnos a pensar.",
     "Poor Charlie's Almanack"),
    ("No se supone que sea fácil. Cualquiera que lo encuentre fácil es estúpido.",
     "Citado por Howard Marks en sus memos"),
    ("Si no incorporás la matemática elemental de la probabilidad, vas por la vida como un hombre de una sola pierna en un "
     "concurso de patadas.",
     "Charla en USC, 1994"),
    ("No tengo nada que agregar.",
     "Su respuesta habitual en las asambleas de Berkshire Hathaway"),
    ("La primera regla es que tenés que tener múltiples modelos, porque si tenés uno o dos, vas a torturar la realidad "
     "hasta que encaje en ellos.",
     "Charla en USC, 1994"),
]


def frase_de_la_semana(hoy=None):
    hoy = hoy or date.today()
    anio, semana, _ = hoy.isocalendar()
    return FRASES[(anio * 53 + semana) % len(FRASES)]
